# Configuration Railway — E-Courtier

Projet Railway `considerate-cat`, environnement `production`.

| Service | Dépôt | Domaine public (inchangé) |
|---|---|---|
| `E-courtier-back` | `2a-business/E-courtier-back` | `e-courtier-back-production.up.railway.app` |
| `E-courtier-web` | `2a-business/E-courtier-web` | `e-courtier-web-production.up.railway.app` |

Base de données : PostgreSQL Neon (hors Railway). Aucun service de base de données Railway.

> Railway déploie depuis GitHub. Les modifications décrites ici doivent être poussées dans les deux dépôts ;
> les réglages « tableau de bord » ci-dessous se font dans Railway → service → *Settings* / *Variables*.

---

## 1. Backend `E-courtier-back`

### 1.1 Volume persistant (photos et justificatifs)

| Réglage | Valeur (constatée le 2026-10-19 vers 23:00 UTC, en lecture seule) |
|---|---|
| Volume | `e-courtie-image` (nom affiché ; `RAILWAY_VOLUME_NAME=e-courtier-back-volume` dans le conteneur), attaché à `E-courtier-back` — ext4, 434 Mo |
| **Chemin de montage** | **`/app/media`** (`RAILWAY_VOLUME_MOUNT_PATH=/app/media`) |
| **`MEDIA_ROOT` attendu** | **`/app/media`** (déduit automatiquement de `RAILWAY_VOLUME_MOUNT_PATH`) |
| `PRIVATE_MEDIA_ROOT` attendu | `/app/media/private` (déduit automatiquement) |
| `MEDIA_URL` | `/media/` (inchangé) |

Disposition du volume :

```
/app/media/                       ← racine du volume = MEDIA_ROOT
├── listings/<annonce>/<uuid>.jpg ← photos + miniatures, diffusées publiquement sous /media/listings/…
├── private/verification/…        ← justificatifs, JAMAIS diffusés (API authentifiée uniquement)
└── lost+found/                   ← créé par le système de fichiers, jamais diffusé
```

Pourquoi cette disposition :

- `/app/media` est exactement `BASE_DIR / "media"`, l'emplacement par défaut du code déjà déployé : les photos
  téléversées depuis le montage du volume (2 fichiers le 2026-10-19 à 22:52, sous `listings/a8c6c687-…/`) gardent
  le même nom en base et seront servies sans aucune migration de fichiers ;
- Railway n'autorise qu'**un** volume par service : les justificatifs doivent être sur ce même volume pour être
  persistés. Le code actuellement déployé les écrit dans `/app/private_media`, **hors volume** (perdus à chaque
  redéploiement) ; le nouveau code les écrit dans `/app/media/private` ;
- la diffusion publique fonctionne par **liste blanche** : seul `listings/` est servi (`PUBLIC_MEDIA_PREFIXES`),
  tout autre chemin du volume répond 404. `prod.py` refuse de démarrer si `PRIVATE_MEDIA_ROOT` vaut `MEDIA_ROOT`,
  en est un parent, ou se trouve dans `listings/`.
- **Ne pas définir** `MEDIA_ROOT` / `PRIVATE_MEDIA_ROOT` dans Railway : les valeurs ci-dessus sont déduites du
  montage. Le volume monté au même endroit que le dossier `media/` du dépôt ne masque aucun code (`media/` est
  ignoré par git).

**Diffusion des images** : par Django (`apps/media/views.py`, route `/media/<chemin>` active en production avec le
stockage local), en flux (`FileResponse`, sans chargement complet en mémoire), `Cache-Control: public,
max-age=31536000, immutable`, `Last-Modified` + réponses 304, `X-Content-Type-Options: nosniff`,
`Cross-Origin-Resource-Policy: cross-origin`. Les URL renvoyées par l'API sont absolues :
`https://e-courtier-back-production.up.railway.app/media/listings/<annonce>/<uuid>.jpg`.
Les justificatifs passent uniquement par `GET /api/v1/verification/documents/<id>/file/` (authentification,
contrôle d'accès, `no-store`, flux).

Conséquences d'un volume sur Railway (à connaître) :

- **une seule instance** : un volume ne peut pas être partagé entre réplicas (garder `numReplicas = 1`) ;
- un redéploiement implique une **courte interruption** (l'ancienne instance libère le volume avant que la
  nouvelle démarre) ;
- les volumes ne sont **pas montés pendant le build** : seul le conteneur d'exécution y a accès.

### 1.2 Build, démarrage, santé

| Réglage (Settings) | Valeur |
|---|---|
| Builder | Railpack (inchangé) |
| Root directory | vide (racine du dépôt) |
| **Custom Build Command** | `python manage.py check --deploy && python manage.py collectstatic --noinput` |
| **Custom Start Command** | **vide** — le `Procfile` du dépôt fournit `gunicorn config.wsgi:application --config gunicorn.conf.py` |
| Pre-deploy Command | **vide** (aucune migration automatique, voir §3) |
| **Healthcheck Path** | `/health/` |
| Healthcheck Timeout | 60 s |
| Restart policy | On failure, 10 essais (inchangé) |
| Replicas | 1 (obligatoire avec un volume) |

Notes :

- `collectstatic` est déjà présent dans la commande de build actuelle (ajouté le 2026-10-19) ; on y ajoute
  `check --deploy` qui bloque le build en cas d'erreur de configuration (secrets, HTTPS, fournisseur LLM inconnu…).
  Les avertissements (ex. `security.W021` préchargement HSTS, `media.W001` au build car le volume n'est pas
  monté pendant la construction) n'arrêtent pas le build. Les variables Railway sont disponibles au build.
- État constaté au déploiement du 2026-10-19 22:49 : Build Command = `python manage.py collectstatic --noinput`
  (d'où `/django-admin/login/` → 200), aucune Start Command, donc démarrage Railpack par défaut
  `python manage.py migrate && gunicorn …` (logs : « Running migrations », « Using worker: sync », 1 worker). Le `Procfile` la remplace (vérifié avec
  `railpack info` 0.41.0). Si une *Custom Start Command* est saisie dans le tableau de bord, elle a priorité sur le
  `Procfile` : elle doit alors être identique à la ligne `web:` du `Procfile`.
- `railway.json` (Config as Code) n'est volontairement **pas** utilisé : Railway l'a déprécié (fin de prise en
  charge annoncée le 2026-12-01).

### 1.3 Variables d'environnement

Légende : ✅ en place et cohérente (constat du 2026-10-19) · ➕ à ajouter · ✏️ à corriger · ➖ à retirer.
Aucune valeur secrète n'est indiquée ici.

| Variable | État | Valeur attendue / remarque |
|---|---|---|
| `DJANGO_ENV` | ✅ | `production` |
| `DJANGO_SETTINGS_MODULE` | ✅ | `config.settings.prod` (facultative) |
| `DJANGO_SECRET_KEY` | ✅ (✏️ facultatif) | ≥ 40 caractères aléatoires. Se termine par un saut de ligne : sans effet fonctionnel ; si on la ressaisit sans ce caractère, toutes les sessions sont invalidées. |
| `DJANGO_ALLOWED_HOSTS` | ✅ | `e-courtier-back-production.up.railway.app` |
| `DATABASE_URL` | ✏️ | URL Neon **pooled** (`-pooler`, `sslmode=require`). **Commence par 2 espaces** : à ressaisir proprement (tolérée aujourd'hui par Python, fragile). |
| `DATABASE_URL_DIRECT` | ➖ (facultatif) | Lue nulle part sur Railway : `scripts/neon_init.sh` la lit dans un **fichier local** passé en argument ; `config/settings/test.py` (jamais chargé en production) s'en sert comme garde-fou, déjà couvert par `DATABASE_URL` sans `-pooler`. **Avant de la retirer, conserver sa valeur** (gestionnaire de mots de passe ou `.env.production.local`) : elle est indispensable aux migrations (§3) ; elle reste aussi disponible dans la console Neon. Contient des espaces et un saut de ligne parasites. |
| `CORS_ALLOWED_ORIGINS` | ✅ | `https://e-courtier-web-production.up.railway.app` |
| `CSRF_TRUSTED_ORIGINS` | ✅ | idem |
| `FRONTEND_URL` | ✅ | idem (liens des e-mails) |
| `REFRESH_COOKIE_SAMESITE` / `REFRESH_COOKIE_SECURE` | ✅ | `None` / `true` (domaines distincts) |
| `PAYMENT_SIMULATION_ENABLED` | ✅ | `false` |
| `WAVE_PAYMENT_LINK` | ✅ | Lien marchand Wave Business `https://pay.wave.com/…` (présent depuis le 2026-10-19) |
| `RAILWAY_VOLUME_MOUNT_PATH` | ✅ automatique | `/app/media`, fournie par Railway (volume attaché) — ne pas la créer à la main |
| `MEDIA_ROOT` / `PRIVATE_MEDIA_ROOT` | ne pas définir | Déduites : `/app/media` et `/app/media/private` |
| `EMAIL_HOST` | ➕ | Serveur SMTP du fournisseur choisi |
| `EMAIL_PORT` | ➕ | `587` (STARTTLS) ou `465` (SSL) |
| `EMAIL_USE_TLS` / `EMAIL_USE_SSL` | ➕ | `true`/`false` pour 587, `false`/`true` pour 465 (exclusifs) |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | ➕ | Identifiants SMTP du fournisseur (secret) |
| `DEFAULT_FROM_EMAIL` | ➕ | Ex. `E-Courtier <no-reply@VOTRE-DOMAINE>` — domaine **vérifié** chez le fournisseur ; `.local`/`example` refusés |
| `EMAIL_TIMEOUT` | facultative | `10` (défaut) |
| `EMAIL_BACKEND` | ne pas définir | SMTP par défaut en production ; console/fichier/mémoire refusés au démarrage |
| `LLM_PROVIDER` | ✅ (✏️ pour activer l'IA) | `rules` aujourd'hui ; `gemini` pour activer Gemini |
| `LLM_MODEL` | ➕ si Gemini | Identifiant de modèle **disponible sur votre compte Google AI** (ex. de `.env.example` : `gemini-2.5-flash-lite`, à vérifier) |
| `LLM_API_KEY` | ➕ si Gemini | Clé API Google AI Studio (secret, serveur uniquement — jamais côté React) |
| `LLM_GEMINI_DISABLE_THINKING`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `LLM_MAX_RETRIES`, `LLM_COOLDOWN_SECONDS`, `ASSISTANT_*` | ✅ | Valeurs de `.env.example` ; plafonds journaliers : `ASSISTANT_GLOBAL_DAILY_REQUESTS=120`, `ASSISTANT_GLOBAL_DAILY_PROVIDER_CALLS=200` |
| `WEB_CONCURRENCY` | ➕ (facultative) | `2` (défaut) — à réduire à `1` si la mémoire du plan est juste |
| `GUNICORN_THREADS` | facultative | `4` (défaut) |
| `GUNICORN_TIMEOUT` | facultative | `30` (défaut) |
| `MEDIA_CACHE_SECONDS` | facultative | `31536000` (défaut, photos immuables) |
| `RENTAL_APPLICATION_REQUIRED_DOCS` | facultative | `ID_CARD\|PASSPORT` (défaut : une pièce d'identité) — groupes séparés par `,`, alternatives par `\|` ; type inconnu = build refusé |
| `MAX_APPLICATION_DOCUMENTS` | facultative | `15` pièces par dossier locatif |
| `TEST_DATABASE_URL` | ne jamais définir | Interdite en production |

Comportement si les variables optionnelles manquent :

- **SMTP absent** : l'application démarre ; `POST /api/v1/auth/password-reset/` répond `503 email_not_configured`
  (message clair côté interface) au lieu d'annoncer un envoi qui n'a pas lieu.
- **Gemini partiellement configuré** (`LLM_PROVIDER=gemini` sans clé ou sans modèle) : `check --deploy` affiche
  l'avertissement `assistant.W001` et l'assistant reste en mode règles, affiché comme tel. Une valeur inconnue
  (`LLM_PROVIDER=gemni`) est une erreur `assistant.E001` qui arrête le build.

---

## 2. Frontend `E-courtier-web`

| Réglage | Valeur |
|---|---|
| Builder | Railpack (inchangé) : `npm install`, `npm run build`, service par Caddy |
| Build / Start Command | **vides** (Railpack) |
| Fichier de serveur | `Caddyfile.template` à la racine du dépôt (Railpack l'utilise à la place de son modèle) |
| Healthcheck Path (recommandé) | `/health` |

| Variable | État | Remarque |
|---|---|---|
| `VITE_API_URL` | ✅ | `https://e-courtier-back-production.up.railway.app` — lue **au build** : tout changement exige un redéploiement du frontend |
| `VITE_MAP_TILE_URL` / `VITE_MAP_ATTRIBUTION` | ✅ | Tuiles OpenStreetMap publiques : à remplacer par un fournisseur de tuiles si le trafic augmente |

Le `Caddyfile.template` ajoute (comme `vercel.json`, ignoré sur Railway) : `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security`, cache `immutable` sur `/assets/*`
et `Cache-Control: no-cache` sur le reste (index.html, routes du SPA, `sw.js`).

---

## 3. Migrations (Neon)

Principe : **aucune migration automatique** au démarrage ni au déploiement. Elles sont appliquées
explicitement, depuis un poste de confiance, avec l'URL Neon **directe** (sans `-pooler`) : les migrations
utilisent des verrous et des transactions longues mal adaptés au pooler en mode transaction.

**Migration à appliquer pour ce lot : `applications 0001_initial`** (dossier locatif) — additive uniquement
(4 nouvelles tables, 3 contraintes ; aucune table existante modifiée). Elle doit être appliquée **avant** le
déploiement du nouveau backend : sans elle, les routes `/api/v1/applications/…` répondent 500 (le reste du site
fonctionne). L'ancien code ignore ces tables : l'appliquer en avance est sans risque. Au dernier démarrage, toutes
les autres migrations étaient appliquées (« No migrations to apply »).

Procédure (cette migration et les suivantes) :

1. Créer un fichier local non versionné, ex. `.env.production.local` (couvert par `.env.*` dans `.gitignore`),
   contenant les variables de production et `DATABASE_URL_DIRECT` (URL directe, `?sslmode=require`).
2. Vérifier la cible et le plan, sans écrire :
   `scripts/neon_init.sh .env.production.local <hôte-neon-direct> ecourtier`
   — le script contrôle l'hôte et la base (`db_target`), exécute `check --deploy`, affiche `migrate --plan`, et
   **demande une confirmation explicite** (saisie de l'hôte, puis « BASE EXISTANTE » si la base n'est pas vide)
   avant toute écriture.
3. Ordre recommandé : migrations **additives** (nouvelles colonnes/tables) **avant** le déploiement du code qui les
   utilise ; suppressions de colonnes dans un déploiement ultérieur.
4. Faire une sauvegarde / une branche Neon avant toute migration non triviale (fonction « branch » de Neon).

---

## 4. Étapes de déploiement (à exécuter après validation)

Railway déploie automatiquement la branche `main` de chaque dépôt à chaque push (constaté : `branch=main`
pour les deux services). **Pousser sur `main` = déployer.** D'où une branche de travail, fusionnée seulement au
moment voulu.

0. **Préparer les commits** (sans déployer) : une branche `fix/production-readiness` dans chaque dépôt, poussée sur
   GitHub (aucun déploiement : Railway ne suit que `main`). Revue du diff sur GitHub.
1. **Backend — volume** : ✅ fait (monté sur `/app/media`). Ne pas le déplacer : le code attend ce chemin.
   Avant le déploiement, **ne pas téléverser de justificatifs** : l'ancien code les écrit hors volume.
2. **Backend — réglages Railway** : Build Command `python manage.py check --deploy && python manage.py collectstatic --noinput`,
   Start Command **vide** (Procfile), Healthcheck `/health/` (§1.2). Ces réglages s'appliqueront au prochain déploiement.
3. **Backend — variables** : ressaisir `DATABASE_URL` sans les espaces initiaux ; SMTP si un fournisseur est prêt ;
   Gemini si souhaité ; `RENTAL_APPLICATION_REQUIRED_DOCS` seulement pour changer le défaut (§1.3). Modifier une
   variable redéploie le code **actuel** (sans effet fonctionnel) : regrouper les modifications.
4. **Neon — migration `applications 0001`** depuis le poste local, avec le code de la branche (§3) :
   `scripts/neon_init.sh .env.production.local <hôte-neon-direct> ecourtier` → vérifier que le plan ne contient
   que `applications.0001_initial`, confirmer.
5. **Backend — déploiement** : fusionner `fix/production-readiness` dans `main` (E-courtier-back). Logs de build :
   `check --deploy` sans erreur, `collectstatic` OK. Logs d'exécution : `Using worker: gthread`, **aucune** ligne
   `Running migrations`.
6. **Validation backend** (checklist §5, partie A).
7. **Frontend — déploiement** : fusionner dans `main` (E-courtier-web) ; validation (checklist §5, partie B).
   Le frontend appelle `/api/v1/applications/…` : ne pas le déployer avant le backend.
8. **Photos existantes** : republier les photos de l'annonce existante (voir §6).

Retour arrière : Railway → service → *Deployments* → redéployer le déploiement précédent (ou `git revert` sur
`main`). La migration `applications 0001` peut rester en place : l'ancien code ignore ces tables (ne pas la
défaire, ce qui supprimerait les dossiers déposés). Les photos restent compatibles dans les deux sens (même
chemin `/app/media/listings/…`), mais l'ancien code ne les diffuse pas (404) et écrit les justificatifs hors volume ;
éviter les téléversements de justificatifs pendant un retour arrière.

---

## 5. Checklist de validation post-déploiement

Ne cocher qu'après observation réelle en production.

**A. Backend**

- [ ] `GET /health/` → 200 ; healthcheck Railway vert.
- [ ] Logs de démarrage : `gthread`, 2 workers, aucune migration exécutée ; messages INFO non classés en erreur.
- [ ] Dans le conteneur : `railway ssh -s E-courtier-back -- df -h /app/media` montre le volume ;
      `python manage.py check --deploy` sans `media.W001`/`media.W002` ; après le premier justificatif,
      `ls /app/media/private/verification` le montre sur le volume.
- [ ] `GET /django-admin/login/` → 200 ; la feuille `admin/css/base.<empreinte>.css` → 200.
- [ ] Publier une photo de test sur une annonce brouillon → l'URL renvoyée répond 200 `image/jpeg`,
      `Cache-Control: public, max-age=31536000, immutable`.
- [ ] Redéployer le backend (sans changement) → la photo de test répond toujours 200 (persistance du volume).
- [ ] Supprimer la photo de test → son URL répond 404.
- [ ] La photo téléversée le 2026-10-19 à 22:52 (`/media/listings/a8c6c687-…/7170424c….jpg`, 404 avant
      déploiement) → 200.
- [ ] Justificatif : `GET /media/private/<chemin du justificatif>` → 404 ; `GET /api/v1/verification/documents/<id>/file/`
      → 401 sans session, 403 pour un autre compte, 200 `no-store` pour le propriétaire ou un admin.
- [ ] `python manage.py media_integrity --details` (via `railway ssh`) : liste des photos sans fichier (voir §6).
- [ ] `GET /api/v1/assistant/info/` → `provider` = `rules` ou `gemini` selon la configuration voulue.
- [ ] Si Gemini activé : une question dans l'assistant → mention « Critères analysés par l'IA » ; puis
      `GET /api/v1/admin/assistant/usage/` (admin) → `recent_calls ≥ 1`, `recent_errors = 0`.
- [ ] Si SMTP configuré : réinitialisation de mot de passe sur un compte de test → e-mail reçu, lien vers
      `https://e-courtier-web-production.up.railway.app/reinitialiser-mot-de-passe?...` ; aucun lien dans les logs.
- [ ] Sans SMTP : la même demande affiche « momentanément indisponible » (503), sans faux succès.
- [ ] Dossier locatif (comptes de test : un client, le propriétaire de l'annonce, un autre propriétaire) :
      visite confirmée → « Constituer mon dossier » ; transmission refusée tant que la pièce d'identité manque ;
      pièce déposée → `ls /app/media/private/applications/` la montre sur le volume ; transmission → notification
      reçue par le propriétaire ; l'autre propriétaire obtient 403 sur le dossier et sur la pièce ;
      `GET /media/private/applications/…` → 404 ; complément demandé → retransmission → acceptation ou refus motivé
      visibles dans l'historique côté client.
- [ ] Paiement (compte client de test, sans payer) : « Payer avec Wave » ouvre `pay.wave.com` ; la page propose
      ensuite la déclaration ; un second clic ne crée pas de seconde tentative ; le dossier reste « En attente ».
- [ ] Paiement réel contrôlé (petit montant, compte de test, avec accord) : déclaration → rapprochement dans
      Wave Business → confirmation admin → contrat généré.

**B. Frontend**

- [ ] `curl -I https://e-courtier-web-production.up.railway.app/` → `X-Frame-Options: DENY`,
      `Referrer-Policy`, `Cache-Control: no-cache`.
- [ ] Un fichier `/assets/*.js` → `Cache-Control: public, max-age=31536000, immutable`.
- [ ] Route profonde (`/logements/<id>`) → 200 (SPA).
- [ ] Parcours : accueil → annonce (photos visibles) → connexion → rafraîchissement de page connecté
      (cookie de session) sur **Chrome, Firefox et Safari/iOS**.

---

## 6. Médias : récupération, limites, évolution

**Fichiers existants — état vérifié (lecture seule)** :

- 2026-10-19 vers 02:10 UTC : le conteneur ne contenait ni `/app/media` ni `/app/private_media`. Les photos du
  2026-10-15 (2 photos, 4 fichiers avec miniatures, annonce `a8c6c687-…`) et les justificatifs de vérification
  avaient été écrits dans le conteneur du 2026-10-15, remplacé par les redéploiements du 2026-10-19.
- 2026-10-19 vers 23:00 UTC, après montage du volume : `/app/media` contient uniquement `lost+found/` et
  **une nouvelle photo** (image + miniature, 22:52) de la même annonce. Les 4 anciens fichiers n'y sont pas ;
  `/app/private_media` n'existe pas.
- Conclusion : les anciens fichiers sont **non récupérables** depuis Railway (aucune copie trouvée). La nouvelle
  photo est intacte et sera servie dès le déploiement. Après déploiement :

1. `python manage.py media_integrity --details` liste les éléments sans fichier (lecture seule) ;
2. le propriétaire supprime les photos cassées depuis son tableau de bord et les republie (fichiers d'origine) ;
3. les justificatifs perdus ne peuvent plus être consultés par l'administration ; l'annonce reste vérifiée
   (décision déjà enregistrée). Une nouvelle soumission peut être demandée au propriétaire si nécessaire.

**Diffusion par le backend — limites** : les photos sont servies par Django (`apps/media/views.py`) en flux
(`FileResponse`), avec un cache navigateur d'un an et revalidation `If-Modified-Since`. Chaque photo occupe
un thread gunicorn le temps du transfert (photos ≤ ~1 Mo après recompression). Avec 2 workers × 4 threads,
une rafale de pages riches en photos peut concurrencer les appels API.

**Si le trafic augmente** (images toujours hébergées sur Railway) : placer un CDN devant le domaine du backend
(ex. domaine personnalisé `api.<domaine>` derrière Cloudflare) avec une règle de cache sur `/media/*` — les
en-têtes `immutable` permettent un cache quasi total, le volume Railway restant l'origine. Augmenter ensuite
`GUNICORN_THREADS` si nécessaire. Le passage à un stockage objet reste possible (`STORAGE_BACKEND=s3`) mais
n'est pas requis.

**Domaine personnalisé (recommandé)** : `up.railway.app` est un suffixe public ; le frontend et l'API sont
donc deux « sites » distincts et le cookie de rafraîchissement est un cookie tiers (`SameSite=None`), que Safari
et certains réglages de Chrome bloquent. Avec `app.<domaine>` et `api.<domaine>`, le cookie redevient
« même site » (`REFRESH_COOKIE_SAMESITE=Lax`) ; mettre alors à jour `DJANGO_ALLOWED_HOSTS`,
`CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `FRONTEND_URL` et `VITE_API_URL`.
