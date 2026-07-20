# Blog de Laurent

Site Hugo, theme PaperMod, bilingue francais/anglais (francais par defaut,
anglais sous /en/).

## Demarrage local

    hugo server -D

Puis ouvrir http://localhost:1313

## Ecrire un nouvel article

    hugo new content posts/mon-nouveau-post/index.md

Editer le fichier cree dans content/posts/mon-nouveau-post/index.md,
passer `draft: false` quand il est pret a publier.

Pour la version anglaise du meme article, creer
content/posts/mon-nouveau-post/index.en.md dans le meme dossier (bundle
partage : les images/ressources du dossier servent aux deux langues).
Meme principe pour une page racine comme about.md -> about.en.md.

## Ajouter des scripts telechargeables (nouveau projet)

Un dossier par projet sous content/scripts/, pour ne pas melanger les
scripts de differents projets sur une seule page :

    content/scripts/mon-projet/
        index.md          (description, cablage, prerequis, code)
        index.en.md        (traduction)
        mon_script.py       (fichier reel, telechargeable a /scripts/mon-projet/mon_script.py)

Lien de telechargement dans le markdown : `[Télécharger](mon_script.py)`
(chemin relatif au bundle). La page d'index content/scripts/_index.md
liste automatiquement tous les projets.

## Deploiement (Cloudflare Pages)

1. Pousser ce repo sur GitHub.
2. Sur Cloudflare Pages : "Create a project" > connecter le repo GitHub.
3. Build command : hugo --minify
   Build output directory : public
   Variable d'environnement : HUGO_VERSION = 0.147.9
4. Ajouter le domaine personnalise dans l'onglet "Custom domains" du projet Pages.

## A adapter avant publication

- hugo.yaml : baseURL (mettre le vrai nom de domaine), socialIcons (mettre le vrai lien GitHub)
- content/about.md : la bio
