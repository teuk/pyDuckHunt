# Métriques Prometheus et dashboard Grafana

Coin publie des agrégats Prometheus dans un fichier régulier remplacé atomiquement.
Le fichier ne contient ni pseudo, ni identité IRC, ni message reçu. Les seuls labels
sont des ensembles fermés : version, état du processus, état du transport, type de
vol et conclusion du dernier vol.

Le service `pyduckhunt-metrics.service` lit ce fichier en lecture seule et expose
uniquement `http://127.0.0.1:9817/metrics`. Il n’accepte aucune connexion distante,
n’écrit rien et tourne sous l’utilisateur `mediabot` sans capacité système.

Prometheus collecte la cible avec le job `pyduckhunt`. Le dashboard provisionné
porte l’UID stable `pyduckhunt-coin` et sélectionne une source Prometheus existante
par variable Grafana. Il présente la fraîcheur, la connexion IRC, l’activité
agrégée, le calendrier et les erreurs d’exploitation.

## Contrats d’exploitation

- Une métrique absente ou trop ancienne est un défaut d’observation, pas une raison
  de modifier l’état du jeu.
- L’échec d’une publication de métriques ne bloque ni la persistance, ni les
  réponses IRC.
- Le port 9817 reste lié à la boucle locale.
- La configuration Prometheus doit passer le `promtool` de la même installation
  avant tout signal de rechargement.
- Le propriétaire, le groupe et le mode du fichier Prometheus sont conservés lors
  du remplacement atomique.
- Le dashboard ne doit contenir aucun identifiant de joueur.

## Vérifications rapides

```sh
curl -fsS http://127.0.0.1:9817/-/healthy
curl -fsS http://127.0.0.1:9817/metrics | head
/home/prometheus/promtool check config /home/prometheus/prometheus.yml
systemctl is-active pyduckhunt@beta.service pyduckhunt-metrics.service prometheus grafana-server
```
