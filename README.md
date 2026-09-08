# F-Droid repository

The index, metadata and deploy for a self-hosted F-Droid repository carrying
several apps.

Apps are not built here. Each app repository builds and signs its own APK and
publishes it as a GitHub Release asset; `publish.yml` collects those, rebuilds
the index and rsyncs it to the server.

```
app repo ──build──▶ sign ──▶ GitHub Release ──┐
app repo ──build──▶ sign ──▶ GitHub Release ──┼──▶ this repo ──▶ fdroid update ──▶ server
app repo ──build──▶ sign ──▶ GitHub Release ──┘
```

## Why the split

The index key is per-repository, not per-app. Kept in each app repo it would
have to be copied everywhere, and a compromise of any one app would let an
attacker forge the index for all of them. Here it exists in one place, and an
app repository holds only its own APK signing key.

It also solves something per-app publishing cannot: two apps publishing at once
would each pull the index down, regenerate it and push, and the second would
overwrite the first. GitHub concurrency groups are per-repository, so only a
single repo owning the deploy can serialize it.

## Adding an app

1. Add an entry to `apps.yml` and a `metadata/<applicationId>.yml`.
2. Have the app publish a signed APK named `<applicationId>_<versionCode>.apk`
   as a release asset. That filename is the whole contract — the app can be
   built with anything.
3. Fill in `signer` once the app's signing key exists.

`signer` is checked before an APK is accepted, and written into the metadata as
`AllowedAPKSigningKeys` so fdroid enforces it too. An empty `signer` is accepted
with a warning, which is a reasonable bootstrap state and a bad steady state:
it is the only thing between a compromised app repository and a malicious APK
in this index.

## Triggers

- `repository_dispatch` with `event_type: publish` — how an app repo asks for
  an immediate publish after a release. Needs a token with access here.
- Every six hours — the safety net for apps that cannot dispatch, and how a
  release published during an outage eventually lands.
- Manually, from the Actions tab.

## Settings

Secrets:

| name | |
|---|---|
| `FDROID_KEYSTORE_B64` | the index key, `base64 -w0 < index.p12` |
| `FDROID_KEYSTORE_PASS` | its password |
| `DEPLOY_SSH_KEY` | private key for `fdroid@fdroid.ccptr.dev` |
| `DEPLOY_SSH_KEY_PASS` | its passphrase, if it has one |

Variables:

| name | |
|---|---|
| `FDROID_KEY_ALIAS` | index key alias |
| `FDROID_REPO_NAME` | display name |
| `FDROID_REPO_URL` | `https://fdroid.ccptr.dev/repo` |
| `FDROID_ARCHIVE_URL` | `https://fdroid.ccptr.dev/archive` |
| `FDROID_SERVERWEBROOT` | `fdroid@fdroid.ccptr.dev:fdroid/` |

`GH_TOKEN` for collecting assets is the workflow's own token, which is enough
for public app repositories. A private one needs a PAT with `contents:read`.

## The server

Static files only; nothing executes there and no key lives there.

```sh
sudo useradd -r -m -d /srv/fdroid -s /bin/bash fdroid
sudo install -d -o fdroid -g fdroid /srv/fdroid/web /srv/fdroid/web/fdroid
sudo pacman -S nginx-mainline certbot certbot-nginx rsync
sudo certbot --nginx -d fdroid.ccptr.dev

# useradd creates the home 0700, which nginx cannot traverse: every request
# 403s, including for world-readable files. 711 lets it through to the web
# root without making the home listable, and leaves .ssh at 700.
sudo chmod 711 /srv/fdroid
```

nginx wants `root /srv/fdroid/web/fdroid;` and `autoindex off;`, so the repo is served
at `/repo` rather than `/fdroid/repo` — the extra segment is for repos living
under a general site, and f-droid.org itself serves `/repo`. Restrict the deploy
key in
`/srv/fdroid/.ssh/authorized_keys`:

```
command="rrsync /srv/fdroid/web",restrict ssh-ed25519 AAAA... deploy
```

Read **and** write, not `rrsync -wo`: the publish job pulls the repo down before
regenerating the index, and `fdroid deploy` rsyncs with `--delete-after`.

The rrsync root is `/srv/fdroid/web` — a subdirectory, deliberately not
`/srv/fdroid`, which is the user's home. rrsync blocks only `..` and pins its
root; it has no protection for dotfiles. Rooted at the home, the key could
overwrite `~/.ssh/authorized_keys`, or drop a `~/.bashrc`, which the forced
command executes because bash reads it when sshd runs it non-interactively.

`serverwebroot` must be a **relative** path (`host:fdroid/`). rrsync rejects an
absolute one, and fdroidserver appends a trailing slash to whatever you give it,
so `host:` becomes `host:/` and is refused. The final path segment has to be
`fdroid` or fdroidserver exits on its own `standardwebroot` check.

## Users add the repo as

```
https://fdroid.ccptr.dev/repo?fingerprint=<sha256 of the index certificate>
```

```sh
keytool -list -v -keystore index.p12 -alias index \
  | sed -n 's/.*SHA256: //p' | tr -d ':' | tr 'A-Z' 'a-z'
```
