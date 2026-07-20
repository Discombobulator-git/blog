---
title: "Faire parler un ventilateur de plafond : reverse engineering RF avec un CC1101 et un Raspberry Pi 5"
date: 2026-07-18T10:00:00+02:00
draft: false
tags: ["RF", "SDR", "CC1101", "Raspberry Pi", "domotique", "reverse engineering"]
categories: ["projets"]
summary: "Reproduire le signal d'une telecommande de ventilateur de plafond avec un module CC1101 et un Raspberry Pi 5, jusqu'au pilotage vocal via Alexa. Recit complet, y compris les galeres."
---

Il y a des projets qui semblent triviaux sur le papier. Celui-ci en faisait partie : capturer le signal radio d'une télécommande de ventilateur de plafond, le rejouer avec un module CC1101 piloté depuis un Raspberry Pi, puis brancher tout ça à Alexa pour piloter le ventilo à la voix. Trois lignes de cahier des charges. Plusieurs semaines de reverse engineering.

Voici le récit complet, avec les fausses pistes, les vrais blocages, et le code qui tourne aujourd'hui en production dans le salon.

## Le matériel

Un module **CC1101** (433,92 MHz, modulation OOK) relié en SPI à un **Raspberry Pi 5**, surnommé RaspiLite. Câblage classique : CS sur GPIO8, CLK sur GPIO11, MOSI sur GPIO10, MISO sur GPIO9. La broche GDO0, qui porte le signal OOK brut, devait initialement aller sur GPIO25, mais cette broche s'est révélée endommagée sur le Pi. Bascule sur GPIO24.

Pour observer et capturer les signaux, deux outils : un dongle RTL-SDR couplé à GQRX pour regarder le spectre en direct, et un analyseur logique Kingst LA1010 pour capturer précisément les trames émises par la vraie télécommande.

## Premier piège : le Raspberry Pi 5 change les règles du jeu

La première embûche est arrivée avant même de parler de RF. Sur Pi 5, la puce RP1 qui gère les GPIO change fondamentalement l'accès matériel. Résultat : `pigpio`, la bibliothèque de référence pour ce genre de timing précis, ne fonctionne plus, puisqu'elle dépend d'un accès direct aux registres BCM qui n'existent plus de la même façon.

Deuxième déception : `lgpio.tx_wave()`, censé générer un signal PWM matériel précis, s'est révélé cassé lui aussi. Au SDR, les niveaux ne basculaient jamais après la toute première impulsion.

La solution retenue a été plus artisanale : du **bit-banging manuel**, avec `lgpio.gpio_write()` piloté par une boucle d'attente active basée sur `time.perf_counter()`. Pas de `time.sleep()`, qui a bien trop de jitter sous un Linux non temps-réel pour des impulsions de 300 et 700 microsecondes. Le résultat mesuré a été un timing quasi parfait.

```python
def busy_wait(seconds):
    """Attente active haute precision (time.sleep() a trop de jitter sous Linux
    non temps-reel pour des impulsions de 300/700us)."""
    target = time.perf_counter() + seconds
    while time.perf_counter() < target:
        pass
```

## Le bruit qu'on s'inflige à soi-même

En écoute, la capture RX était noyée sous du bruit parasite. Un comptage simple des fronts détectés a révélé quelque chose d'inattendu : environ 467 fronts par seconde avec le Pi débranché du fil GDO0, contre 1055 par seconde une fois branché. Le simple fait de relier le fil ajoutait plus du double de bruit électromagnétique, généré par le Pi lui-même.

Premier réflexe adopté : débrancher systématiquement le Pi du fil GDO0 pendant les phases de capture pure.

Le vrai correctif est venu ensuite, côté configuration du CC1101 : réduire le gain RX maximal autorisé via le registre `AGCCTRL2`, en passant de `0x43` à `0x63`, soit environ 9 dB de réduction du gain LNA maximum. Les captures sont passées de "pleines de trames-bruit" à 100% de trames propres.

## Un compteur caché dans le suffixe

Chaque bouton de la télécommande envoie une trame de 32 bits. En comparant plusieurs captures d'un même bouton, un motif est apparu : les 25 à 26 premiers bits restent parfaitement stables d'une pression à l'autre. Ce sont eux qui identifient le bouton. Mais les 6 à 8 derniers bits changent à chaque nouvelle pression, tout en restant cohérents entre les répétitions d'une même pression.

Signature typique d'un compteur anti-répétition, un rolling code léger. Conséquence concrète : d'anciens codes enregistrés dans le script étaient devenus obsolètes sur ce suffixe, alors que le préfixe restait exploitable tel quel.

## Le vrai blocage : un bit invisible

C'est là que le projet a vraiment buté. Des codes fraîchement recapturés, un signal RF visiblement propre sur GQRX, et pourtant rien ne se passait sur le vrai ventilateur. Même testé à bout portant, ce qui a au moins permis d'écarter une hypothèse de portée ou de gain d'antenne, et de recentrer l'enquête sur la structure de la trame elle-même plutôt que sur la puissance d'émission.

En reprenant les fichiers CSV bruts de l'analyseur logique à la main, en contournant un bug du script de décodage automatique, la cause est apparue : chaque trame fait en réalité **33 bits, pas 32**. Le 33ème bit est une impulsion haute nette qui alterne strictement 0, 1, 0, 1 à chaque répétition au sein d'une même pression de bouton, un comportement identique confirmé sur les trois boutons testés.

Le script de décodage perdait ce bit parce que sa portion basse fusionnait électriquement avec le silence entre deux trames, sans transition détectable. Les 32 bits stockés étaient donc corrects, mais la trame envoyée était structurellement trop courte, et le récepteur du ventilateur la rejetait silencieusement.

Le correctif : ajouter un bit de fin togglé, qui part de `0` puis alterne à chaque répétition, juste après les 32 bits du code et avant le silence inter-trame.

```python
def bit_banging_tx(h, bits, repeats):
    """Chaque trame reelle fait 33 bits, pas 32 : un bit supplementaire
    termine la trame, perdu par le script d'analyse car sa portion basse
    fusionne avec le silence inter-trame. Ce bit alterne 0/1/0/1 a chaque
    repetition sur toutes les captures observees."""
    toggle_bit = '0'
    for r in range(repeats):
        for bit in bits + toggle_bit:
            if bit == '1':
                lgpio.gpio_write(h, GDO0_PIN, 1)
                busy_wait(LONG_US / 1e6)
                lgpio.gpio_write(h, GDO0_PIN, 0)
                busy_wait(SHORT_US / 1e6)
            else:
                lgpio.gpio_write(h, GDO0_PIN, 1)
                busy_wait(SHORT_US / 1e6)
                lgpio.gpio_write(h, GDO0_PIN, 0)
                busy_wait(LONG_US / 1e6)
        lgpio.gpio_write(h, GDO0_PIN, 0)
        time.sleep(INTERFRAME_GAP_US / 1e6)
        toggle_bit = '1' if toggle_bit == '0' else '0'
```

Le résultat n'a pas tardé. Le bouton `onoff` a fait réagir le vrai ventilateur (bip, changement d'état) juste après ce correctif. Puis `lumiere`, `v2` et `v1` ont suivi, confirmés fonctionnels avec exactement le même fix générique, sans traitement spécifique par bouton.

D'autres ajustements plus mineurs ont accompagné cette percée : le registre `IOCFG0` corrigé de `0x2E` (haute impédance) à `0x2D` (entrée de données TX asynchrone), l'ajout d'un strobe `SCAL` de calibration du synthétiseur avant `STX` qui a nettoyé un signal auparavant sale et large bande observé sur GQRX, et une valeur de `PATABLE` réajustée de `0xC0` à `0xC6`.

## Brancher tout ça à Alexa

Restait l'objectif final : le pilotage vocal. Deux options étaient sur la table. Une Skill Alexa personnalisée hébergée sur AWS Lambda, écartée car plus lourde à maintenir. Ou **Home Assistant en Docker** couplé au composant `emulated_hue`, qui fait passer Home Assistant pour un pont Philips Hue aux yeux d'Alexa, avec découverte locale et sans compte cloud payant. C'est cette deuxième option qui a été retenue, la plus simple qui marche.

La chaîne complète mise en place :

1. Un conteneur Docker Home Assistant.
2. Un petit serveur HTTP natif, `ventilo_bridge.py`, tournant hors Docker pour garder un accès direct au SPI et aux GPIO, qui expose un endpoint par bouton et lance le script de transmission en sous-processus.
3. Dans la configuration de Home Assistant, des `rest_command` qui appellent ce serveur, et des switches template optimistes qui appellent ces `rest_command`.
4. `emulated_hue` configuré pour exposer ces switches comme des ampoules Hue virtuelles.

```python
class Handler(BaseHTTPRequestHandler):
    def _handle(self):
        bouton = self.path.strip("/")
        if bouton not in BOUTONS_EXPOSES:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f"Bouton inconnu: {bouton}\n".encode())
            return
        try:
            result = subprocess.run(
                [sys.executable, SCRIPT, bouton],
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            self.send_response(504)
            self.end_headers()
            self.wfile.write(b"Timeout pendant la transmission\n")
            return
        if result.returncode == 0:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"OK: {bouton}\n".encode())
        else:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(result.stderr.encode())
```

Un piège attendait encore au tournant. Avec `expose_by_default: false`, lister une entité sous `entities:` avec juste un `name:` ne suffit pas à l'exposer réellement à l'API Hue. L'API renvoyait `{}` alors que les switches existaient bien côté Home Assistant. Il faut ajouter explicitement `hidden: false` sous chaque entité. L'alternative aurait été de passer `expose_by_default: true`, mais cela expose absolument tout, y compris une vingtaine d'entités sans rapport comme des switches de médias.

```yaml
emulated_hue:
  host_ip: 192.168.1.37
  listen_port: 80
  expose_by_default: false
  entities:
    switch.ventilo:
      name: Ventilo
    switch.lumiere_ventilo:
      name: Lumiere Ventilo
```

Le test bout-en-bout a été fait avec un appel `curl` reproduisant exactement ce qu'Alexa enverrait, un `PUT` sur `/api/anyuser/lights/1/state`. Le ventilateur a réagi. La chaîne complète, de l'API Hue au CC1101 en passant par Home Assistant et le serveur pont, était validée.

Un `crontab -e @reboot` relance automatiquement le serveur pont au démarrage. Il ne reste qu'une étape non automatisable : la découverte manuelle des appareils depuis l'application mobile Alexa.

## Où ça en est, et la suite

À ce stade, la chaîne complète fonctionne bout en bout : commande vocale ou API Hue, switch Home Assistant, `rest_command`, serveur pont Python, CC1101 en bit-banging, réception RF par le ventilateur. Les quatre boutons `onoff`, `lumiere`, `v1` et `v2` sont opérationnels.

La prochaine étape, décidée mais pas encore commencée, est un portage de la partie émission sur un **ESP32-WROOM-32** déjà commandé. L'idée est de s'affranchir des soucis de timing du Pi 5, qui obligent au bit-banging manuel, grâce au périphérique RMT matériel de l'ESP32 conçu justement pour générer des signaux avec un timing précis nativement. Cela ouvrirait aussi la porte à une intégration ESPHome native dans Home Assistant, sans passer par le détour `emulated_hue`.

## Ce qu'il faut retenir

Ce projet illustre bien un principe classique du reverse engineering RF : le signal peut paraître propre à l'oscilloscope ou au SDR tout en étant structurellement incomplet. Un bit invisible dans l'outil d'analyse, parce qu'il se fond dans le silence inter-trame, peut suffire à bloquer 100% des réceptions côté destinataire.

Et parfois, la solution la plus simple qui marche (un composant `emulated_hue` plutôt qu'une Skill Alexa cloud) vaut mieux qu'une infrastructure plus "propre" sur le papier mais plus lourde à maintenir.

## Mise à jour : portage sur Raspberry Pi Zero W

Plutôt que l'ESP32 initialement envisagé, la partie émission a finalement été portée sur un **Raspberry Pi Zero W**. Sur cette puce BCM2835 classique (sans le RP1 du Pi 5), `pigpio` fonctionne nativement : le bit-banging manuel a été remplacé par une génération de signal en wave DMA via `pigpio.wave_send_once()`, avec un timing garanti au microseconde près et sans boucle d'attente active bloquante.

Le script gère maintenant neuf commandes (`onoff`, `lumiere`, `v1` à `v6`, `inversion`), et le pont HTTP a été réécrit en Flask (`ventilo_api.py`) plutôt qu'en serveur `BaseHTTPRequestHandler` fait main.

Les scripts qui tournent aujourd'hui en production sont disponibles sur la [page Scripts]({{< ref "/scripts/cc1101-ventilo-alexa/index.md" >}}) de ce blog, avec le détail du câblage et des prérequis pour qui voudrait les réutiliser.
