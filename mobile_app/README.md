# Station Irrigation Mobile

Application Android Expo / React Native pour afficher la station SCADA Python sur le même réseau Wi-Fi.

## Fonctions

- Connexion à l'adresse locale affichée dans la barre « téléphone » de l'application Python.
- Actualisation des mesures, météo, zones de goutte-à-goutte et alertes toutes les 3 secondes.
- Carte schématique de la parcelle avec humidité moyenne, secteurs secs et sélection des secteurs A–D.
- Commandes d'ouverture et de fermeture des vannes simulées depuis la liste des zones, avec retour en mode automatique.
- Envoi de la position du téléphone au serveur pour choisir la météo locale.
- Notifications Android locales lorsque de nouvelles alertes arrivent pendant que l'application est ouverte.
- Adresse de la station mémorisée sur le téléphone.

Les commandes de zones et les boutons de diagnostic agissent uniquement sur le
simulateur Python. Une commande de vanne met la simulation en mode manuel ; le bouton
« Revenir au mode automatique » restaure le pilotage simulé. Le serveur ne commande
aucune électrovanne, ESP32 ni aucun appareil réel.

La carte actuelle est une vue de démonstration basée sur les mesures simulées par secteur
(une valeur par zone A–D). Elle ne représente pas encore de mesures individuelles de
sondes ESP32 et ne possède pas de coordonnées géographiques de capteurs. La salinité
reste indiquée comme non mesurée, car aucun capteur de salinité n'est connecté.

Touchez un secteur de la carte pour afficher son humidité, son débit mesuré/attendu,
sa pression, la hausse d'humidité depuis l'ouverture de la ligne et des outils de test.
Les tests simulent un goutteur bouché (débit trop faible) ou l'absence de hausse de
l'humidité après irrigation. La détection utilise des seuils de démonstration : débit
inférieur à 30 % du débit attendu, pression sous 0,28 bar, ou hausse d'humidité inférieure
à 0,5 point après 4 minutes simulées. Les anomalies apparaissent sur la carte, dans le
panneau du secteur, dans les alertes et dans les notifications activées. « Rétablir le
secteur » enlève le défaut simulé. Le test ouvre uniquement la vanne simulée du secteur
pour lancer son cycle de mesure. Ces commandes changent uniquement le simulateur Python ;
aucune électrovanne ni aucun appareil réel n'est commandé.

Le tableau de bord Python propose aussi un onglet « Agriculture » avec les mesures
par secteur et les mêmes essais de défaut. Après une mise à jour,
fermez puis relancez `station_irrigation_scada.py` et rechargez l'application Expo Go
(touche `r` dans le terminal Expo) pour afficher l'interface actuelle.

Pour une installation réelle, il reste à relier au serveur les mesures des sondes
capacitatives et débitmètres par secteur, la pression, les coordonnées de chaque sonde
et, si désiré, la salinité. Les seuils doivent ensuite être étalonnés selon le sol,
la culture, la profondeur des sondes et le débit des goutteurs.

## Démarrage avec Expo Go

1. Démarrez `station_irrigation_scada.py` sur l'ordinateur et autorisez Python sur le réseau privé si le pare-feu Windows le demande.
2. Connectez l'ordinateur et le téléphone au même réseau Wi-Fi.
3. Installez Node.js 22.13+ (ou 24.3+) sur l'ordinateur et Expo Go depuis le Play Store sur le téléphone.
4. Depuis ce dossier, exécutez `npm install`, puis `npx expo start`.
5. Scannez le QR code avec Expo Go.
6. Dans l'application, entrez l'adresse complète visible dans la fenêtre SCADA, par exemple `http://192.168.1.20:8765`.

N'utilisez pas `localhost` : sur le téléphone, il désigne le téléphone lui-même. Vérifiez également que le pare-feu Windows autorise le port affiché par la station.

Les notifications ne sont pas des notifications push distantes : pour recevoir les mesures et nouvelles alertes, l'application doit rester ouverte au premier plan. La météo nécessite une connexion Internet sur l'ordinateur.

## Vérifications et APK

- `npm run typecheck` vérifie les types TypeScript.
- `npx expo run:android` permet de créer/exécuter un build Android local après installation d'Android Studio et du SDK Android. L'autorisation HTTP locale est activée dans `app.json`.
