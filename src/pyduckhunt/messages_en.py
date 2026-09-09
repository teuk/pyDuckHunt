"""English presentation catalogue.

Terminology adapted from the supplied Duck Hunt Tcl 2.11 English pack,
© 2015–2016 MenzAgitat, CC BY-NC-SA 3.0; pyDuckHunt additions retain the
current game rules. Dynamic names, clocks, URLs and IRC targets are not keys.
"""

EN = {
    "fusil d'assaut": 'assault rifle',
    'arc': 'bow',
    'initialisation': 'initialization',
    '\x0314[+{0} événements]\x0f': '\x0314[+{0} events]\x0f',
    ' (confisquée définitivement)': ' (permanently confiscated)',
    ' (confisquée)': ' (confiscated)',
    ' (enrayée)': ' (jammed)',
    ' (première expiration dans {0})': ' (first expiry in {0})',
    ' (vie : {0})': ' (life: {0})',
    ' (également #{0})': ' (also #{0})',
    ' ; +{0}s aux nouveaux vols': ' ; +{0}s for new flights',
    ' ; en local : telnet localhost ': ' ; locally: telnet localhost ',
    " [bon d'achat]": ' [voucher]',
    ' [coupon promo.]': ' [discount coupon]',
    ' [munition recyclée]': ' [recycled ammo]',
    ' [rechargement auto.]': ' [auto reload]',
    ' niv. {0} (progression : {1}/{2})': ' lv. {0} (progress: {1}/{2})',
    ' sur {0}': ' on {0}',
    ' {0}{1} pts {2}': ' {0}{1} pts {2}',
    '!bang': '!bang',
    '!duckrank [limite]': '!duckrank [limit]',
    '!duckstats [nick]': '!duckstats [nick]',
    '!inventory [nick]': '!inventory [nick]',
    '!lastduck': '!lastduck',
    '!pain': '!pain',
    '!reload': '!reload',
    '!shop [id [cible]]': '!shop [id [target]]',
    '#{0} fin={1}': '#{0} ends={1}',
    '*sifflote*': '*whistle*',
    '+{0} fatigue': '+{0} fatigue',
    '+{0} pts précision': '+{0} accuracy pts',
    '.dccstat                        IP, ports, offres et sessions DCC': '.dccstat                        IP, ports, offers and DCC sessions',
    '.duck [#canal]                 lance un canard sans déplacer le planning': '.duck [#channel]                launch a duck without moving the schedule',
    '.duckplanning                   les 24 horaires, pains, appeaux et réveil effectif': '.duckplanning                   all 24 times, bread, calls and effective wake-up',
    '.fields                         champs acceptés par .setplayer': '.fields                         fields accepted by .setplayer',
    '.game                           vol, planning et état DuckHunt': '.game                           flight, schedule and DuckHunt state',
    '.giveammo <nick> [n]            donne 1 à 100 munitions, sans dépasser la capacité': '.giveammo <nick> [n]             give 1 to 100 bullets, within capacity',
    '.givemag <nick> [n]             donne 1 à 100 chargeurs, sans dépasser la réserve': '.givemag <nick> [n]              give 1 to 100 magazines, within reserve capacity',
    '.goldenduck [#canal]           lance un canard doré (alias : .golden)': '.goldenduck [#channel]          launch a golden duck (alias: .golden)',
    '.passwd                          remplace le mot de passe de la partyline': '.passwd                         replace the partyline password',
    ".player <nick>                  profil complet d'un joueur": '.player <nick>                  full player profile',
    '.quit                            ferme la session': '.quit                           close the session',
    '.returnweapon <nick>             restitue une arme confisquée': '.returnweapon <nick>            return a confiscated weapon',
    '.setplayer <nick> <champ> <v>    modifie un champ borné (liste avec .fields)': '.setplayer <nick> <field> <v>    update a bounded field (list with .fields)',
    '.status                         Coin, IRC, persistance et sessions': '.status                         Coin, IRC, persistence and sessions',
    '.summary                        top 5, profils, inventaires et dernier tireur': '.summary                        top 5, profiles, inventories and last shooter',
    ".unjam <nick>                    déraie l'arme": '.unjam <nick>                   unjam the weapon',
    '.who                            opérateurs connectés': '.who                            connected operators',
    '10 xp': '10 xp',
    '100 xp': '100 xp',
    '20 xp': '20 xp',
    '30 xp': '30 xp',
    '40 xp': '40 xp',
    '50 xp': '50 xp',
    (
        '<!doctype html>\n'
        '<html lang="fr" data-pyduckhunt-ranking="1">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '  <meta name="generator" content="Coin / pyDuckHunt">\n'
        '  <meta name="color-scheme" content="dark">\n'
        '  <meta name="theme-color" content="#071013">\n'
        '  <meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src '
        "'unsafe-inline'; img-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'; "
        'frame-ancestors \'self\'">\n'
        '  <title>Classement pyDuckHunt — i/o</title>\n'
        '  <meta name="description" content="Classement public et statistiques des chasseurs '
        'pyDuckHunt sur i/o.">\n'
        '  <style>{0}{1}{2}</style>\n'
        '</head>\n'
        '<body>\n'
        '  <!-- PYDUCKHUNT_RANKING_PAGE_V1 -->\n'
        '  <div class="site-noise" aria-hidden="true"></div>\n'
        '  <header class="site-header">\n'
        '    <div class="site-container header-inner">\n'
        '      <a class="brand" href="/" aria-label="i/o — accueil"><span '
        'class="brand-mark">i/o</span><span class="brand-copy">Epiknet<br>mediabot_v3</span></a>\n'
        '      <nav class="primary-nav" aria-label="Navigation principale"><a '
        'href="/">Accueil</a><a href="/#mediabot">Mediabot</a><a '
        'href="/DuckHunt/">DuckHunt</a><a href="/#connexion">Connexion</a></nav>\n'
        '      <div class="header-status"><i></i><span>Coin en ligne</span></div>\n'
        '    </div>\n'
        '  </header>\n'
        '  <div class="duckhunt-subnav">\n'
        '    <div class="site-container duckhunt-subnav-inner">\n'
        '      <a class="duckhunt-subbrand" href="/DuckHunt/"><span class="target-mark" '
        'aria-hidden="true">◎</span> Coin / pyDuckHunt</a>\n'
        '      <nav aria-label="Navigation pyDuckHunt"><a href="/DuckHunt/">Vue d’ensemble</a><a '
        'href="/DuckHunt/shop/">Boutique</a><a href="/DuckHunt/levels/">Niveaux</a><a '
        'href="/DuckHunt/commands/">Commandes</a><a href="/DuckHunt/rankings/" '
        'aria-current="page">Classement</a></nav>\n'
        '    </div>\n'
        '  </div>\n'
        '  <main>\n'
        '    <section class="ranking-hero">\n'
        '      <div class="site-container hero-grid">\n'
        '        <div>\n'
        '          <div class="eyebrow"><span></span>TABLEAU DE CHASSE · DONNÉES DURABLES</div>\n'
        '          <h1>Classement des <em>chasseurs.</em></h1>\n'
        '          <p>Les places suivent le nombre de canards touchés, puis le meilleur temps et '
        'l’identité IRC canonique pour départager les égalités.</p>\n'
        '        </div>\n'
        '        <div class="hero-signal" '
        'aria-hidden="true"><span>RANK</span><b>01</b><i>\\_O&lt;</i></div>\n'
        '      </div>\n'
        '    </section>\n'
        '    <section class="site-container summary-grid" aria-label="Résumé du '
        'classement">{3}</section>\n'
        '    <section class="site-container ranking-section">\n'
        '      <div class="section-heading"><div><span>LE PODIUM</span><h2>Les fines gâchettes '
        'du canal.</h2></div><p>Actualisé automatiquement par Coin après chaque changement '
        'durable.</p></div>\n'
        '      {4}\n'
        '      <div class="table-heading"><div><span>TABLEAU COMPLET</span><h2>Tous les '
        'chasseurs</h2></div><time datetime="{5}">Mise à jour : {6}</time></div>\n'
        '      {7}\n'
        '      <p class="ranking-note">XP désigne le solde actuellement disponible. La précision '
        'affichée est celle de l’arme au niveau courant.</p>\n'
        '    </section>\n'
        '  </main>\n'
        '  <footer class="site-footer"><div class="site-container '
        'footer-inner"><span>io.teuk.org · Coin / pyDuckHunt</span><span>Classement généré '
        'depuis l’état durable du jeu.</span></div></footer>\n'
        '</body>\n'
        '</html>\n'
    ): (
        '<!doctype html>\n'
        '<html lang="en" data-pyduckhunt-ranking="1">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '  <meta name="generator" content="Coin / pyDuckHunt">\n'
        '  <meta name="color-scheme" content="dark">\n'
        '  <meta name="theme-color" content="#071013">\n'
        '  <meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src '
        "'unsafe-inline'; img-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'; "
        'frame-ancestors \'self\'">\n'
        '  <title>pyDuckHunt rankings — i/o</title>\n'
        '  <meta name="description" content="Public pyDuckHunt hunter rankings and statistics.">\n'
        '  <style>{0}{1}{2}</style>\n'
        '</head>\n'
        '<body>\n'
        '  <!-- PYDUCKHUNT_RANKING_PAGE_V1 -->\n'
        '  <div class="site-noise" aria-hidden="true"></div>\n'
        '  <header class="site-header">\n'
        '    <div class="site-container header-inner">\n'
        '      <a class="brand" href="/" aria-label="i/o — home"><span '
        'class="brand-mark">i/o</span><span class="brand-copy">Epiknet<br>mediabot_v3</span></a>\n'
        '      <nav class="primary-nav" aria-label="Main navigation"><a href="/">Home</a><a '
        'href="/#mediabot">Mediabot</a><a href="/DuckHunt/">DuckHunt</a><a '
        'href="/#connexion">Connect</a></nav>\n'
        '      <div class="header-status"><i></i><span>Coin online</span></div>\n'
        '    </div>\n'
        '  </header>\n'
        '  <div class="duckhunt-subnav">\n'
        '    <div class="site-container duckhunt-subnav-inner">\n'
        '      <a class="duckhunt-subbrand" href="/DuckHunt/"><span class="target-mark" '
        'aria-hidden="true">◎</span> Coin / pyDuckHunt</a>\n'
        '      <nav aria-label="Navigation pyDuckHunt"><a href="/DuckHunt/">Overview</a><a '
        'href="/DuckHunt/shop/">Shop</a><a href="/DuckHunt/levels/">Levels</a><a '
        'href="/DuckHunt/commands/">Commands</a><a href="/DuckHunt/rankings/" '
        'aria-current="page">Rankings</a></nav>\n'
        '    </div>\n'
        '  </div>\n'
        '  <main>\n'
        '    <section class="ranking-hero">\n'
        '      <div class="site-container hero-grid">\n'
        '        <div>\n'
        '          <div class="eyebrow"><span></span>HUNTING RECORD · DURABLE DATA</div>\n'
        '          <h1>Hunter <em>rankings.</em></h1>\n'
        '          <p>Places are ordered by ducks hit, then best time and canonical IRC identity '
        'to break ties.</p>\n'
        '        </div>\n'
        '        <div class="hero-signal" '
        'aria-hidden="true"><span>RANK</span><b>01</b><i>\\_O&lt;</i></div>\n'
        '      </div>\n'
        '    </section>\n'
        '    <section class="site-container summary-grid" aria-label="Ranking '
        'summary">{3}</section>\n'
        '    <section class="site-container ranking-section">\n'
        '      <div class="section-heading"><div><span>THE PODIUM</span><h2>The channel’s '
        'sharpest shooters.</h2></div><p>Updated automatically by Coin after each durable '
        'change.</p></div>\n'
        '      {4}\n'
        '      <div class="table-heading"><div><span>FULL LEADERBOARD</span><h2>All '
        'hunters</h2></div><time datetime="{5}">Updated: {6}</time></div>\n'
        '      {7}\n'
        '      <p class="ranking-note">XP is the currently available balance. Accuracy is the '
        'weapon’s base accuracy at the current level.</p>\n'
        '    </section>\n'
        '  </main>\n'
        '  <footer class="site-footer"><div class="site-container '
        'footer-inner"><span>io.teuk.org · Coin / pyDuckHunt</span><span>Rankings generated from '
        'durable game state.</span></div></footer>\n'
        '</body>\n'
        '</html>\n'
    ),
    (
        '<article class="podium-card place-{0}"><span class="place">#{1:02d}</span><div '
        'class="podium-name">{2}</div><div '
        'class="podium-score"><strong>{3}</strong><span>canards</span></div><div '
        'class="podium-meta"><span>Niv. '
        '{4}</span><span>{5}</span><span>{6}</span></div></article>'
    ): (
        '<article class="podium-card place-{0}"><span class="place">#{1:02d}</span><div '
        'class="podium-name">{2}</div><div '
        'class="podium-score"><strong>{3}</strong><span>ducks</span></div><div '
        'class="podium-meta"><span>Lv. {4}</span><span>{5}</span><span>{6}</span></div></article>'
    ),
    (
        '<details class="inventory-details" data-inventory="1"><summary title="{0}" '
        'aria-label="Afficher l’inventaire de {1}"><span class="inventory-icon" '
        'aria-hidden="true">🎒</span><span class="sr-only">Afficher '
        'l’inventaire</span></summary><div '
        'class="inventory-panel"><strong>{2}</strong><ul>{3}</ul></div></details>'
    ): (
        '<details class="inventory-details" data-inventory="1"><summary title="{0}" '
        'aria-label="Show the inventory of {1}"><span class="inventory-icon" '
        'aria-hidden="true">🎒</span><span class="sr-only">Show inventory</span></summary><div '
        'class="inventory-panel"><strong>{2}</strong><ul>{3}</ul></div></details>'
    ),
    (
        '<div class="empty-state"><b>\\_O&lt;</b><strong>Aucun chasseur classé.</strong><span>Le '
        'premier tir réussi ouvrira le tableau.</span></div>'
    ): (
        '<div class="empty-state"><b>\\_O&lt;</b><strong>No ranked hunters.</strong><span>The '
        'first successful shot will open the leaderboard.</span></div>'
    ),
    (
        '<div class="ranking-table-shell" aria-label="Tableau complet du '
        'classement"><table><caption>Classement complet des chasseurs '
        'pyDuckHunt</caption><colgroup><col class="col-place"><col class="col-hunter"><col '
        'class="col-hunt"><col class="col-time"><col class="col-progress"><col '
        'class="col-weapon"><col class="col-condition"><col class="col-ammunition"><col '
        'class="col-shots"><col class="col-incidents"><col '
        'class="col-inventory"></colgroup><thead><tr>{0}</tr></thead><tbody>{1}</tbody></table></'
        'div>'
    ): (
        '<div class="ranking-table-shell" aria-label="Full ranking table"><table><caption>Full '
        'pyDuckHunt hunter rankings</caption><colgroup><col class="col-place"><col '
        'class="col-hunter"><col class="col-hunt"><col class="col-time"><col '
        'class="col-progress"><col class="col-weapon"><col class="col-condition"><col '
        'class="col-ammunition"><col class="col-shots"><col class="col-incidents"><col '
        'class="col-inventory"></colgroup><thead><tr>{0}</tr></thead><tbody>{1}</tbody></table></'
        'div>'
    ),
    '<div class="table-empty">En attente du premier chasseur.</div>': '<div class="table-empty">Waiting for the first hunter.</div>',
    '=== Coin · résumé DuckHunt ===': '=== Coin · DuckHunt summary ===',
    '=== Dernier tireur ===': '=== Last shooter ===',
    (
        'Actif 1h, conservé à chaque envol. Attraction renforcée ; départ des nouveaux canards '
        'retardé de {0}s.'
    ): 'Active for 1h and kept through every flight. Stronger attraction; new ducks stay {0}s longer.',
    'Action #{0}: {1}, auteur={2}, échéance={3}.': 'Action #{0}: {1}, by={2}, due={3}.',
    'Activity misses={0} wild={1} empty={2} fatigue={3:.2f}% carried={4} credit={5}': 'Activity misses={0} wild={1} empty={2} fatigue={3:.2f}% carried={4} credit={5}',
    'Arme': 'Weapon',
    'Arme enrayée': 'Jammed gun',
    'Armure': 'Armor',
    "Attention : {0}/{1} pain(s) expirent avant ou à la prochaine échéance d'envol connue ({2}). ": 'Warning: {0}/{1} bread piece(s) expire before or at the next known flight deadline ({2}). ',
    "Aucun envol de canard n'a encore été enregistré.": 'No duck flight has been recorded yet.',
    'Aucun prochain envol connu : consommation du pain non garantie.': 'No next flight known: bread consumption is not guaranteed.',
    'Aucun prochain envol connu avant recalcul.': 'No next flight known until recalculation.',
    'Aucun tir enregistré.': 'No shot recorded.',
    'BOUM': 'BOOM',
    (
        'Base=24 vols/jour | pains actifs={0} | attraction : plan à {1} créneaux (sans garantie '
        "d'envol pendant l'heure)."
    ): (
        'Base=24 flights/day | active bread={0} | attraction: {1}-slot plan (no guaranteed '
        'flight during the hour).'
    ),
    'Boutique: !shop [id [cible]]': 'Shop: !shop [id [target]]',
    'Boutique: {0} | !shop [id [cible]]': 'Shop: {0} | !shop [id [target]]',
    'COIN': 'QUACK',
    'COUAAAAC': 'QUAAAAC',
    'COUAAAACK': 'QUAAAACK',
    'COUAAAAK': 'QUAAAAK',
    'COUAAAC': 'QUAAAC',
    'COUAAACK': 'QUAAACK',
    'COUAAAK': 'QUAAAK',
    'COUAAC': 'QUAAC',
    'COUAACK': 'QUAACK',
    'COUAAK': 'QUAAK',
    'COUAC': 'QUAC',
    'COUACK': 'QUACK',
    'COUAK': 'QUAK',
    'CUI ?': 'TWEET?',
    'Canard doré': 'Golden duck',
    'Canards dorés': 'Golden ducks',
    'Canards touchés': 'Ducks hit',
    "Ce tir exige un règlement d'incident indisponible.": 'This shot requires incident resolution that is unavailable.',
    "Cet objet n'accepte pas de cible.": 'This item does not accept a target.',
    'Cette cible': 'This target',
    "Chaque canard abattu te rapportera {0} {1} d'xp {2} pendant 24h.": 'Each duck you shoot down earns you {0} {2} XP {1} for 24h.',
    'Charg.': 'Clips',
    'Chasseur': 'Hunter',
    'Chasseurs': 'Hunters',
    'Connexion DCC CHAT expirée.': 'DCC CHAT connection expired.',
    'Connexion DCC CHAT impossible.': 'Cannot connect DCC CHAT.',
    'CôÔT ?': 'CLUCK?',
    'Dernier canard : {0}, il y a {1}.': 'Last duck: {0}, {1} ago.',
    (
        'Disponible 1h ; un morceau consommé par envol s’il est encore valide. Le prochain envol '
        'quotidien ne change pas.'
    ): (
        'Available for 1h; each flight consumes one piece if it is still valid. The next daily '
        'flight stays unchanged.'
    ),
    'Duckplanning {0} — aucun planning quotidien.': 'Duckplanning {0} — no daily schedule.',
    'Décès': 'Deaths',
    'Déflex.': 'Deflect.',
    "Désormais, tu n'encourras plus de pénalités en cas d'accident de chasse.": 'You will no longer incur penalties for hunting accidents.',
    "Effrayé par tout ce bruit, le canard s'échappe.": 'Frightened by so much noise, the duck fled.',
    'Expiration des pains: {0}.': 'Bread expires: {0}.',
    'Fatigue': 'Fatigue',
    (
        'Fields: ammo capacity magazines magazine_capacity fatigue level xp credit jammed '
        'confiscated carried_ducks hits misses wild_shots empty_shots jammed_shots '
        'compulsive_reloads golden_hits deaths.'
    ): (
        'Fields: ammo capacity magazines magazine_capacity fatigue level xp credit jammed '
        'confiscated carried_ducks hits misses wild_shots empty_shots jammed_shots '
        'compulsive_reloads golden_hits deaths.'
    ),
    'Hello ! Bootstrap owner armé pour 10 minutes ; aucun mot de passe ne doit être envoyé sur IRC.': 'Hello! Owner bootstrap enabled for 10 minutes; never send a password over IRC.',
    'Hello world': 'Hello world',
    (
        'Il y a désormais 1 chance sur 10 pour que les munitions utilisées soient recyclées et '
        "que tes tirs n'en consomment pas."
    ): 'Each shot now has a 1 in 10 chance of recycling its ammo and consuming no bullet.',
    "Impossible d'ouvrir l'écoute DCC CHAT.": 'Cannot open the DCC CHAT listener.',
    'Initialisation partyline refusée pour cette identité IRC.': 'Partyline initialization refused for this IRC identity.',
    'Inventaire': 'Inventory',
    'Inventaire de {0}': 'Inventory of {0}',
    'Jeton DCC passif invalide.': 'Invalid passive DCC token.',
    "L'attraction ne garantit pas un envol avant expiration.": 'Attraction does not guarantee a flight before expiry.',
    (
        "La gâchette de ton arme sera bloquée s'il n'y a aucun canard dans les environs afin "
        "d'éviter le gaspillage de munitions. Dure 24h pour 6 utilisations."
    ): (
        'Your trigger locks when there are no ducks around, preventing wasted ammo. Lasts for '
        '24h and 6 uses.'
    ),
    "Lancement refusé : Coin n'est pas connecté à IRC.": 'Launch refused: Coin is not connected to IRC.',
    "Lancement refusé : Coin n'est pas sur {0}.": 'Launch refused: Coin is not on {0}.',
    'Lancement refusé : la persistance est occupée.': 'Launch refused: persistence is busy.',
    'Lancement refusé : un canard est déjà présent.': 'Launch refused: a duck is already present.',
    'Le canard mange un morceau de pain posé sur le canal.': 'The duck eats a piece of bread left on the channel.',
    "Le canard s'échappe. {0}·°'`'°-.,¸¸.·°'`{1}": "The duck escapes. {0}·°'`'°-.,¸¸.·°'`{1}",
    'Le dernier canard a été aperçu il y a {0}.': 'The last duck was spotted {0} ago.',
    "Le risque d'enrayage de ton arme est réduit de moitié pendant 24h.": 'The chance of your weapon jamming is halved for 24h.',
    'Les dégâts de ton arme sont doublés pendant 24h.': 'Damage from your weapon is doubled for 24h.',
    'Les dégâts de ton arme sont triplés pendant 24h.': 'Damage from your weapon is tripled for 24h.',
    'Les effets de la prochaine malédiction seront neutralisés.': 'The next curse will be neutralized.',
    'Lucky Luke': 'Lucky Luke',
    'Lunette pour 6 tirs : +{0} points de précision actuellement.': 'Sight for 6 shots: currently +{0} accuracy points.',
    'Légende: ✓ traité | → prochain quotidien | · à venir.': 'Key: ✓ processed | → next daily | · upcoming.',
    'Légende: ✓ échéance passée du plan actuel (pas un bilan de chasse) | → prochain | · à venir.': 'Key: ✓ elapsed deadline in the current plan (not hunting results) | → next | · upcoming.',
    'Meilleur temps': 'Best time',
    'Mot de passe refusé sur IRC : choisissez-le dans la partyline.': 'Do not send passwords over IRC: choose yours in the partyline.',
    'Mun.': 'Ammo',
    'Niv.': 'Lv.',
    'Niveau': 'Level',
    'Offre DCC CHAT expirée.': 'DCC CHAT offer expired.',
    "Offre DCC indisponible : dcc_public_ip n'est pas configurée.": 'DCC offer unavailable: dcc_public_ip is not configured.',
    'Ouvrez /ctcp Coin CHAT ou /dcc chat Coin': 'Open /ctcp Coin CHAT or /dcc chat Coin',
    'PIOU ?': 'PEEP?',
    'POUÊT': 'HONK',
    'Pains={0} | appeaux/actions={1} | ': 'Bread={0} | calls/actions={1} | ',
    'Partyline déjà initialisée. Utilisez /msg Coin reset si le mot de passe doit être remplacé.': 'Partyline already initialized. Use /msg Coin reset if the password needs replacing.',
    'Pendant 24h, chaque canard abattu fait apparaître un morceau de pain sur le canal.': 'For 24h, every duck you shoot down places a piece of bread on the channel.',
    'Pendant 24h, chaque canard abattu fera apparaître un canard mécanique 10mn après.': 'For 24h, every duck you shoot down summons a mechanical duck 10 minutes later.',
    (
        'Pendant 24h, il y a 1 chance sur 3 pour que les munitions utilisées soient recyclées et '
        "que tes tirs n'en consomment pas."
    ): 'For 24h, each shot has a 1 in 3 chance of recycling its ammo and consuming no bullet.',
    (
        'Pendant 48h, il y a 1 chance sur 2 pour que les munitions utilisées soient recyclées et '
        "que tes tirs n'en consomment pas."
    ): 'For 48h, each shot has a 1 in 2 chance of recycling its ammo and consuming no bullet.',
    'Prochain quotidien={0} | réveil effectif={1} | vol={2}.': 'Next daily={0} | effective wake-up={1} | flight={2}.',
    'Précision': 'Accuracy',
    'QUECK': 'QUECK',
    'Recharg.': 'Reloads',
    'Rechargements compulsifs': 'Compulsive reloads',
    'Réinitialisation armée pour 10 minutes ; aucun mot de passe ne doit être envoyé sur IRC.': 'Reset enabled for 10 minutes; never send a password over IRC.',
    'Réinitialisation partyline refusée pour cette identité IRC.': 'Partyline reset refused for this IRC identity.',
    'Seul un envol plus tôt pourrait les consommer.': 'Only an earlier flight could consume them.',
    (
        'Tes chances de trouver des objets intéressants en fouillant les buissons sont doublées '
        'pendant 24h.'
    ): 'Your chances of finding interesting items in the bushes are doubled for 24h.',
    "Tes tirs ne risquent plus d'effrayer les canards pendant 24h.": 'Your shots will not frighten ducks for 24h.',
    'Tirs': 'Shots',
    'Tirs absorbés': 'Shots absorbed',
    'Tirs déviés': 'Shots deflected',
    'Tirs ratés': 'Missed shots',
    'Tirs reçus': 'Shots received',
    'Tirs sauvages': 'Wild shots',
    'Tirs à vide': 'Empty shots',
    "Ton détecteur de canards t'avertit : un canard vient de s'envoler.": 'Your duck detector warns you: a duck has just appeared.',
    "Trop d'offres DCC CHAT sont déjà en attente.": 'Too many DCC CHAT offers are pending.',
    'Trop de connexions DCC CHAT sont déjà en attente.': 'Too many DCC CHAT connections are pending.',
    'Tu bénéficies de 10% de réduction dans le shop pendant 1 semaine.': 'You get a 10% shop discount for 1 week.',
    'Tu bénéficies de 10% de réduction dans le shop pendant 24h.': 'You get a 10% shop discount for 24h.',
    'Tu bénéficies de 10% de réduction dans le shop pendant 48h.': 'You get a 10% shop discount for 48h.',
    'Tu bénéficies de 25% de réduction dans le shop pendant 1 semaine.': 'You get a 25% shop discount for 1 week.',
    'Tu bénéficies de 25% de réduction dans le shop pendant 24h.': 'You get a 25% shop discount for 24h.',
    'Tu bénéficies de 25% de réduction dans le shop pendant 48h.': 'You get a 25% shop discount for 48h.',
    'Tu bénéficies de 50% de réduction dans le shop pendant 24h.': 'You get a 50% shop discount for 24h.',
    'Tu bénéficies de 50% de réduction dans le shop pendant 48h.': 'You get a 50% shop discount for 48h.',
    "Tu disposes d'une réserve de chargeurs illimitée pendant 24h.": 'You have unlimited spare magazines for 24h.',
    "Tu disposes d'une réserve de chargeurs illimitée pendant 48h.": 'You have unlimited spare magazines for 48h.',
    "Tu es maintenant protégé contre l'éblouissement de manière permanente.": 'You are now permanently protected against glare.',
    (
        "Tu es maintenant protégé contre le sable et le risque d'enrayage de ton arme est réduit "
        'de moitié de manière permanente.'
    ): "You are now permanently protected against sand and your weapon's chance of jamming is halved.",
    "Tu es maintenant protégé contre les seaux d'eau de manière permanente.": 'You are now permanently protected against buckets of water.',
    "Tu es protégé contre l'éblouissement pendant 24h.": 'You are protected against glare for 24h.',
    'Tu ne ressens plus les effets de la fatigue pendant 24h.': 'You no longer feel the effects of fatigue for 24h.',
    'Tu peux désormais charger une munition supplémentaire dans ton arme.': 'You can now load one extra bullet in your weapon.',
    'Tu peux désormais transporter un chargeur supplémentaire.': 'You can now carry one extra magazine.',
    'Tu peux transporter un nombre illimité de canards sans être encombré pendant 24h.': 'You can carry unlimited ducks without being encumbered for 24h.',
    "Tu seras averti par une notice lors de l'envol du prochain canard.": 'You will receive a notice when the next duck appears.',
    'Tu te sens en pleine forme mais un peu surexcité. [surexcité]': 'You feel refreshed but a little overexcited. [overexcited]',
    'Tu te sens en pleine forme.': 'You feel refreshed.',
    "Un canard est en vol depuis {0}; envol dans {1} s'il n'est pas touché.": 'A duck has been flying for {0}; it will escape in {1} unless shot down.',
    'Une offre DCC CHAT est déjà en attente.': 'A DCC CHAT offer is already pending.',
    'Usage : /msg Coin ducklaunch #canal [1] — 1 lance un canard doré.': 'Usage: /msg Coin ducklaunch #channel [1] — 1 launches a golden duck.',
    'Vols {0:02d}-{1:02d}: ': 'Flights {0:02d}-{1:02d}: ',
    'XP disponible': 'Available XP',
    '[ARME CONFISQUÉE : accident de chasse]': '[GUN CONFISCATED: hunting accident]',
    '[Inventaire] ': '[Inventory] ',
    '[accident : -{0} xp]': '[accident: -{0} xp]',
    '[raté : -{0} xp]': '[missed: -{0} xp]',
    '[tir sauvage : -{0} xp]': '[wild fire: -{0} xp]',
    'abattu par {0} en {1}': 'shot down by {0} in {1}',
    'absorbés': 'absorbed',
    'ah que coin coin !': 'quack quack!',
    'allez, je lance un canard': 'all right, here comes a duck',
    "amulette d'abondance": 'amulet of abundance',
    "amulette d'endurance": 'amulet of endurance',
    'amulette de bénédiction': 'amulet of blessing',
    'amulette du boulanger': "baker's amulet",
    'amulette du farceur': "prankster's amulet",
    'amulette du guerrier': "warrior's amulet",
    'amulette du guerrier éternel': "eternal warrior's amulet",
    'anatidaephobe': 'anatidaephobe',
    'aplatisseur de canards': 'duck flattener',
    'appeau': 'duck call',
    'arbalète': 'crossbow',
    "arrêtez, c'est pas ce que vous croyez !": 'stop, it is not what you think!',
    'assommeur de canards': 'duck clobberer',
    'assurance responsabilité civile': 'liability insurance',
    'assurance vie': 'life insurance',
    'atomiseur de canards': 'duck atomizer',
    'aucun': 'none',
    'aucun canal': 'no channel',
    'aucun pain disponible.': 'no bread available.',
    'balle supplémentaire': 'extra bullet',
    "bon d'achat {0} xp": '{0} xp voucher',
    "bon, c'est qui le trou du cul qui a tué mon pote ?!": 'right, which asshole killed my buddy?!',
    'bouffeur de canards': 'duck eater',
    "c'est ici pour le casting ?": 'I am here for the casting',
    "c'est ici que ça canarde ?": 'is this where the shooting happens?',
    "c'est moi que tu regardes, là ? C'EST MOI QUE TU REGARDES ?!": 'are you looking at me? ARE YOU LOOKING AT ME?!',
    'canard': 'duck',
    'canard mécanique': 'mechanical duck',
    'canards': 'ducks',
    'carabine': 'rifle',
    'celui dont les canards ne prononcent pas le nom': 'he whose name ducks dare not speak',
    'cette cible': 'this target',
    'charg.': 'charg.',
    'chargeur supplémentaire': 'extra clip',
    'chargeur étendu': 'extended magazine',
    'chasseur confirmé': 'experienced hunter',
    "chasseur d'élite de la mort qui tue": 'deadly elite hunter',
    "chasseur d'élite de la mort qui tue avant même de tirer": 'elite hunter who kills before firing',
    "chasseur d'élite de la mort qui tue même en dormant": 'elite hunter who kills in his sleep',
    "chasseur d'élite professionnel": 'professional elite hunter',
    "chasseur d'élite qui fout incroyablement les jetons": 'unbelievably terrifying elite hunter',
    "chasseur d'élite qui fout trop les jetons": 'terrifying elite hunter',
    "chasseur d'élite émérite": 'distinguished elite hunter',
    'chasseur de niveau {0}': 'level {0} hunter',
    'chasseur du dimanche': 'weekend hunter',
    'comp.': 'comp.',
    'coupon promo. 10%': '10% discount coupon',
    'coupon promo. 25%': '25% discount coupon',
    'coupon promo. 50%': '50% discount coupon',
    'créneaux traités.': 'processed slots.',
    'de la graisse': 'some grease',
    'des lunettes de soleil': 'sunglasses',
    'des lunettes de soleil incassables': 'indestructible sunglasses',
    'des munitions AP': 'AP ammo',
    'des munitions explosives': 'explosive ammo',
    'des munitions perforantes': 'AP ammo',
    'disséqueur de canards': 'duck dissector',
    'dorés': 'golden',
    'déboîteur de canards': 'duck dislocator',
    'déchiqueteur de canards': 'duck shredder',
    'décortiqueur de canards': 'duck decorticator',
    'découpeur de canards': 'duck chopper',
    'décès': 'deaths',
    'défonceur de canards': 'duck smasher',
    'déglingueur de canards': 'duck wrecking crew',
    'démolisseur de canards': 'duck demolisher',
    'démonteur de canards': 'duck disassembler',
    'dépeceur de canards': 'duck butcher',
    'déplumeur de canards': 'duck plucker',
    'désintégrateur de canards': 'duck disintegrator',
    'détecteur de canards': 'ducks detector',
    'détecteur infrarouge': 'infrared detector',
    'détesteur de canards': 'duck disliker',
    'dévastateur de canards': 'duck devastator',
    'déviés': 'deflected',
    'effrayé par un tir après {0}': 'frightened away by a shot after {0}',
    'emmerdeur de canards': 'duck pest',
    'encombré': 'encumbered',
    'enray.': 'jammed',
    'envolé sans être touché après {0}': 'escaped untouched after {0}',
    'euh... pourquoi vous avez tous une arme dans la main ?': 'uh... why are you all holding guns?',
    'expert en armes à feu': 'firearms expert',
    'expresso': 'espresso',
    'fatigue': 'fatigue',
    'fatigue gain exceeds the bounded player range': 'fatigue gain exceeds the bounded player range',
    'fatigue: {0}{1} (-{2} pts précision)': 'fatigue: {0}{1} (-{2} accuracy pts)',
    'fatigué': 'tired',
    'fusil de chasse': 'shotgun',
    'fusil de précision': 'sniper rifle',
    'fusil à pompe': 'pump-action shotgun',
    'gibecière TARDIS': 'TARDIS game bag',
    'gibecière TARDIS:': 'TARDIS game bag:',
    'gibecière:': 'game bag:',
    'goupillon': 'cleaning brush',
    'graisse': 'grease',
    'grand inquisiteur des palmipèdes': 'grand inquisitor of waterfowl',
    'grande gibecière': 'large game bag',
    'grignotteur de canards': 'duck nibbler',
    'harceleur de canards': 'duck hassler',
    'haïsseur de canards': 'duck hater',
    'horodatage durable {0} ns': 'durable timestamp {0} ns',
    'imperméable': 'raincoat',
    'infusion de camomille': 'chamomile tea',
    'inscrit sur la liste noire de la CCCCC (Coalition Contre le Comité Contre les Canards)': 'blacklisted by the CACAD (Coalition Against the Committee Against Ducks)',
    'item inhabituel': 'unusual item',
    'item légendaire': 'legendary item',
    'item rare': 'rare item',
    'item très rare': 'very rare item',
    "je cherche mon pote, il devait m'attendre ici": 'I am looking for my buddy, he was supposed to meet me here',
    'je ne vous en veux pas': 'I do not hold it against you',
    'je suis invulnérable HAHAHAHA': 'I am invulnerable HAHAHAHA',
    'je suis venu négocier une trêve': 'I came to negotiate a truce',
    'je viens en paix': 'I come in peace',
    'laissez-moi tranquille, je drope des malédictions': 'leave me alone, I drop curses',
    'last-flight provider must return non-negative integer or None': 'last-flight provider must return non-negative integer or None',
    'le canal': 'the channel',
    'le canard': 'the duck',
    'le {0}[CANARD DORÉ]{1}': 'the {0}[GOLDEN DUCK]{1}',
    'lunette': 'sight',
    'lunette de visée': 'sight',
    'lunettes de soleil': 'sunglasses',
    'lunettes soleil': 'sunglasses',
    'malédiction: {0}': 'curse: {0}',
    'membre du CCC (Comité Contre les Canards)': 'member of the CAD (Committee Against Ducks)',
    'miroir': 'mirror',
    'mitraillette': 'submachine gun',
    'morceau': 'piece',
    'morceau de pain': 'piece of bread',
    'morceaux': 'pieces',
    'mun.': 'ammo',
    'mun. AP': 'AP ammo',
    'mun. expl.': 'expl. ammo',
    'munitions explosives': 'explosive ammo',
    'munitions perforantes': 'armor-piercing ammo',
    'mâchouilleur de canards': 'duck chewer',
    "n'ayez pas peur, je ne vous veux aucun mal": 'do not be afraid, I mean you no harm',
    'ne tirez pas, je me rends !': 'do not shoot, I surrender!',
    'ne tirez pas, je ne suis pas armé !': 'do not shoot, I am unarmed!',
    'non': 'no',
    'noob': 'noob',
    'objet': 'item',
    'objet {0}': 'item {0}',
    "on m'a parlé d'un troupeau de touristes avec des pétoires, c'est ici ?": 'I heard about a flock of tourists with guns, is this the place?',
    'oui': 'yes',
    'pain conservé à chaque envol ; +{0}s aux nouveaux vols.': 'bread kept through every flight; +{0}s for new flights.',
    'permis de tuer': 'license to kill',
    'pistolet': 'pistol',
    'poignée de sable': 'handful of sand',
    'point': 'point',
    'points': 'points',
    'pointé du doigt par les canards': 'pointed at by ducks',
    'pourvu que personne ne me remarque...': 'I hope no one will notice me...',
    'poutreur de canards': 'duck wrecker',
    'promeneur armé': 'armed walker',
    'préc.': 'acc.',
    "rachat de l'arme": 'weapon buyback',
    'rateur de canards': 'duck misser',
    'ratés': 'missed',
    'rechargement automatique': 'automatic reload',
    'recherché dans 47 mares': 'wanted in 47 ponds',
    'recycl. mun. (10%)': 'ammo recycler (10%)',
    'recycleur (1/3)': 'recycler (1/3)',
    'recycleur haut de gamme (1/2)': 'premium recycler (1/2)',
    'regardez, là bas ! une diversion !': 'look over there! a distraction!',
    'retourneur de canards': 'inside-out duck turner',
    'reçus': 'received',
    'rituel de purification': 'purification ritual',
    'sabotage': 'sabotage',
    'sauf-conduit': 'safe-conduct pass',
    'sauv.': 'wild',
    "seau d'eau": 'bucket of water',
    'serial duck killer': 'serial duck killer',
    'silencieux': 'silencer',
    'stagiaire': 'trainee',
    'supplémentaire': 'extra',
    'supplémentaires': 'extra',
    'surchargé': 'overloaded',
    'surexcitation': 'overexcitement',
    'surexcité': 'overexcited',
    'syntaxe : {0}': 'syntax: {0}',
    'syst. autolubrifiant': 'self-lubricating system',
    'thermos de café': 'coffee thermos',
    'tirez pas, je suis un fake !': 'do not shoot, I am a fake!',
    'tirez pas, je suis un pigeon !': 'do not shoot, I am a pigeon!',
    'tonique': 'tonic',
    'touriste': 'tourist',
    'tremblements': 'tremors',
    'troueur de canards': 'duck perforator',
    'trèfle à quatre feuilles': 'four-leaf clover',
    'tueur de canards': 'duck killer',
    "un bon d'achat de 10 xp": 'a 10 xp voucher',
    "un bon d'achat de 20 xp": 'a 20 xp voucher',
    "un bon d'achat de 50 xp": 'a 50 xp voucher',
    "un bon d'achat de 75 xp": 'a 75 xp voucher',
    'un chargeur supplémentaire': 'an extra ammo clip',
    'un chargeur étendu': 'an extended magazine',
    'un coupon promotionnel': 'a discount coupon',
    'un coupon promotionnel de 10% (24h)': 'a 10% discount coupon (24h)',
    'un coupon promotionnel de 10% (48h)': 'a 10% discount coupon (48h)',
    'un coupon promotionnel de 10% (7j)': 'a 10% discount coupon (7d)',
    'un coupon promotionnel de 25% (24h)': 'a 25% discount coupon (24h)',
    'un coupon promotionnel de 25% (48h)': 'a 25% discount coupon (48h)',
    'un coupon promotionnel de 25% (7j)': 'a 25% discount coupon (7d)',
    'un coupon promotionnel de 50% (24h)': 'a 50% discount coupon (24h)',
    'un coupon promotionnel de 50% (48h)': 'a 50% discount coupon (48h)',
    'un détecteur de canards': 'a duck detector',
    'un détecteur infrarouge': 'an infrared detector',
    'un grand sac à munitions': 'a large ammo bag',
    'un imperméable indéchirable': 'a tearproof raincoat',
    'un morceau au plus par envol, uniquement avant son expiration.': 'at most one piece per flight, only before it expires.',
    'un objet': 'an item',
    'un objet mystérieux': 'a mysterious item',
    'un parchemin maudit': 'a cursed scroll',
    'un permis de tuer permanent': 'a permanent license to kill',
    'un recycleur de munitions': 'an ammo recycler',
    'un recycleur de munitions (1/3, 24h)': 'an ammo recycler (1/3, 24h)',
    'un recycleur de munitions de grade militaire': 'a military-grade ammo recycler',
    'un recycleur de munitions haut de gamme': 'a premium ammo recycler',
    'un recycleur de munitions haut de gamme (1/2, 48h)': 'a premium ammo recycler (1/2, 48h)',
    'un recycleur de munitions militaire (1/10)': 'a military ammo recycler (1/10)',
    'un silencieux': 'a silencer',
    'un système autolubrifiant militaire': 'a military self-lubricating system',
    'un système autolubrifiant militaire pour ton arme': 'a military self-lubricating system for your weapon',
    'un trèfle à 4 feuilles +{0}': 'a +{0} four-leaf clover',
    'un trèfle à quatre feuilles': 'a four-leaf clover',
    "une Amulette d'Endurance": 'an Amulet of Endurance',
    'une Amulette de Bénédiction': 'an Amulet of Blessing',
    'une Amulette du Boulanger': "a Baker's Amulet",
    'une Amulette du Farceur': "a Prankster's Amulet",
    'une Amulette du Guerrier': "a Warrior's Amulet",
    'une Amulette du Guerrier Éternel': "an Eternal Warrior's Amulet",
    "une amulette d'abondance": 'an amulet of abundance',
    "une amulette d'endurance": 'an amulet of endurance',
    'une amulette de bénédiction': 'an amulet of blessing',
    'une amulette du boulanger': "a baker's amulet",
    'une amulette du farceur': "a prankster's amulet",
    'une amulette du guerrier (24h)': "a warrior's amulet (24h)",
    'une amulette du guerrier éternel (48h)': "an eternal warrior's amulet (48h)",
    'une balle supplémentaire': 'an extra bullet',
    'une cible': 'a target',
    'une gibecière TARDIS': 'a TARDIS game bag',
    'une gibecière TARDIS (24h)': 'a TARDIS game bag (24h)',
    'une lettre C en bois': 'a wooden letter C',
    'une lettre D en bois': 'a wooden letter D',
    'une lettre H en bois': 'a wooden letter H',
    'une lettre K en bois': 'a wooden letter K',
    'une lettre N en bois': 'a wooden letter N',
    'une lettre Q en bois': 'a wooden letter Q',
    'une lettre T en bois': 'a wooden letter T',
    'une lettre U en bois': 'a wooden letter U',
    'une lunette de visée': 'a sight',
    'une lunette de visée pour ton arme': 'a sight for your weapon',
    'verre de gnôle': 'glass of moonshine',
    'vide': 'empty',
    "vous connaissez l'histoire du con qui dit !bang ?": 'have you heard the one about the fool who says !bang?',
    'vous visez vraiment mal...': 'you really cannot aim...',
    'végétarien armé': 'armed vegetarian',
    'vétéran': 'veteran',
    'vêtements secs': 'dry clothes',
    '{0} #{1} lancé sur {2}{3}.': '{0} #{1} launched on {2}{3}.',
    '{0} > Achat : {1} [{2} xp].{3}': '{0} > Purchase: {1} [{2} xp].{3}',
    '{0} > Action administrative refusée.': '{0} > Administrative action refused.',
    '{0} > Action refusée : persistance occupée.': '{0} > Action refused: persistence is busy.',
    '{0} > Arme de {1} confisquée de façon permanente.': "{0} > {1}'s weapon permanently confiscated.",
    "{0} > Arme de {1} confisquée jusqu'à minuit, heure de Paris.": "{0} > {1}'s weapon confiscated until midnight, Paris time.",
    '{0} > Arme de {1} restituée.': "{0} > {1}'s weapon returned.",
    "{0} > C'est raté, tu as tiré {1} trop tard.   {2}[raté : -{3} xp]{4}{5}": '{0} > Missed, you fired {1} too late.   {2}[missed: -{3} xp]{4}{5}',
    "{0} > Cet achat n'est pas utile actuellement.": '{0} > This purchase is not useful right now.',
    '{0} > Cet achat nécessite une cible.': '{0} > This purchase requires a target.',
    "{0} > Cet objet n'existe pas.": '{0} > This item does not exist.',
    "{0} > Cette malédiction t'empêche de recharger.": '{0} > This curse prevents you from reloading.',
    '{0} > En fouillant les buissons autour du canard, tu trouves {1}{2}{3}. {4}{5}': '{0} > By searching the bushes around the duck, you find {1}{2}{3}. {4}{5}',
    '{0} > En fouillant les buissons autour du canard, tu trouves... {1}{2}{3}{4}.{5}': '{0} > By searching the bushes around the duck, you find... {1}{2}{3}{4}.{5}',
    '{0} > Il y a déjà 20 morceaux de pain sur le canal ; achat refusé sans dépense.': '{0} > There are already 20 pieces of bread on the channel; purchase refused without spending XP.',
    '{0} > Je ne connais aucun chasseur portant ce nom.': '{0} > I do not know any hunter by that name.',
    '{0} > Joueur inconnu : {1}.': '{0} > Unknown player: {1}.',
    "{0} > L'arme de {1} est immunisée contre cette nuisance.": "{0} > {1}'s weapon is immune to this nuisance.",
    '{0} > Le canard a survécu. [vie -{1}]{2}': '{0} > The duck survived. [life -{1}]{2}',
    "{0} > Modification de l'arme refusée.": '{0} > Weapon update refused.',
    '{0} > Modification refusée : persistance occupée.': '{0} > Update refused: persistence is busy.',
    (
        "{0} > Par chance tu as raté, mais tu visais qui au juste ? Il n'y a aucun canard dans "
        'le coin...   {1} {2}{3}'
    ): '{0} > Luckily you missed, but who were you aiming at? There is no duck around...   {1} {2}{3}',
    '{0} > Raté. {1}{2}{3}': '{0} > Missed. {1}{2}{3}',
    '{0} > Service occupé ; réessaie dans un instant.': '{0} > Service busy; try again in a moment.',
    '{0} > Ton action est retardée de 5s par une malédiction.': '{0} > A curse delays your action by 5s.',
    '{0} > Ton amulette de bénédiction neutralise la malédiction.': '{0} > Your amulet of blessing neutralizes the curse.',
    '{0} > Ton amulette fait apparaître du pain sur le canal.': '{0} > Your amulet places bread on the channel.',
    '{0} > Ton amulette programme un canard mécanique dans 10mn00s.': '{0} > Your amulet schedules a mechanical duck in 10m00s.',
    "{0} > Ton arme n'a pas besoin d'être rechargée.": '{0} > Your gun does not need reloading.',
    "{0} > Ton arme n'a pas besoin d'être rechargée. | Mun. : {1}/{2} | Charg. : {3}": '{0} > Your gun does not need reloading. | Ammo: {1}/{2} | Clips: {3}',
    '{0} > Trop de commandes ; réessaie dans {1}.': '{0} > Too many commands; try again in {1}.',
    (
        "{0} > Tu achètes et utilises un appeau en échange de {1} points d'xp, ce qui devrait "
        'attirer un canard dans les 10 prochaines minutes.{2}'
    ): (
        '{0} > You buy and use a duck call for {1} xp, which should attract a duck within the '
        'next 10 minutes.{2}'
    ),
    (
        "{0} > Tu achètes un morceau de pain en échange de {1} points d'xp. Il reste disponible "
        "pendant 1h ou jusqu'au prochain envol, qui en consommera un. Ton karma temporaire "
        'augmente aussi de 2,00. Il y a actuellement {2} {3} de pain sur {4}.{5}'
    ): (
        '{0} > You buy a piece of bread for {1} xp. It remains available for 1h or until the '
        'next flight consumes one piece. Your temporary karma also increases by 2.00. There are '
        'currently {2} {3} of bread on {4}.{5}'
    ),
    (
        "{0} > Tu achètes un morceau de pain en échange de {1} points d'xp. Pendant 1h, il "
        "renforce l'attraction et retarde le départ des nouveaux canards de 20s par morceau. Il "
        'reste en place à chaque envol. Karma temporaire : +2,00. Il y a actuellement {2} {3} de '
        'pain sur {4}.{5}'
    ): (
        '{0} > You buy a piece of bread for {1} xp. For 1h, it strengthens attraction and makes '
        'new ducks stay 20s longer per piece. It stays in place through every flight. Temporary '
        'karma: +2.00. There are currently {2} {3} of bread on {4}.{5}'
    ),
    "{0} > Tu achètes un thermos de café en échange de {1} points d'xp. Fatigue : {2} → {3}. {4}{5}": '{0} > You buy a coffee thermos for {1} xp. Fatigue: {2} → {3}. {4}{5}',
    (
        "{0} > Tu achètes un trèfle à quatre feuilles en échange de {1} points d'xp. Ce "
        "porte-bonheur te fera gagner {2} {3} d'xp {4} pour chaque canard abattu pendant 24h.{5}"
    ): (
        '{0} > You buy a four-leaf clover for {1} xp. It earns you {2} {4} XP {3} for each duck '
        'you shoot down for 24h.{5}'
    ),
    (
        "{0} > Tu ajoutes une lunette de visée à ton arme en échange de {1} points d'xp. Lunette "
        'pour 6 tirs : +{2} points de précision actuellement.{3}'
    ): (
        '{0} > You add a sight to your weapon for {1} xp. Sight for 6 shots: currently +{2} '
        'accuracy points.{3}'
    ),
    '{0} > Tu déposes un morceau de pain sur {1}. Il y a actuellement {2} {3} de pain. ': '{0} > You put bread on {1}. There are currently {2} {3} of bread. ',
    '{0} > Tu es à court de chargeurs.': '{0} > You are out of spare magazines.',
    "{0} > Tu n'es pas assez riche pour cet achat.": '{0} > You cannot afford this purchase.',
    '{0} > Tu ne peux pas chasser pour le moment.': '{0} > You cannot hunt right now.',
    (
        '{0} > Tu utilises un appeau. Échéance prévue : {1} (après le vol actif si nécessaire). '
        'Le prochain envol quotidien ne change pas.'
    ): (
        '{0} > You use a duck call. Scheduled for: {1} (after the active flight if necessary). '
        'The next daily flight stays unchanged.'
    ),
    '{0} > Usage : {1}': '{0} > Usage: {1}',
    (
        '{0} > {1}     Tu as eu {2} en {3}, ce qui te fait un total de {4} {5}{6}.     '
        '{7}\\_X<{8}   *COUAC*   {9}[{10} xp]{11}{12}{13}{14}{15}{16}'
    ): (
        '{0} > {1}     You shot down {2} in {3}, which makes a total of {4} {5}{6}.     '
        '{7}\\_X<{8}   *KWAK*   {9}[{10} xp]{11}{12}{13}{14}{15}{16}'
    ),
    "{0} > {1} C'est un {2}[CANARD DORÉ]{3} ! Il a survécu. [vie -{4}]{5}": '{0} > {1} It is a {2}[GOLDEN DUCK]{3}! It survived. [life -{4}]{5}',
    '{0} > {1} est déjà actif.': '{0} > {1} is already active.',
    "{0} > {1} n'a pas d'arme.": '{0} > {1} has no weapon.',
    "{0} > {1} n'est pas là.": '{0} > {1} is not here.',
    "{0} > {1}*BOUM*{2} Ton arme vient d'exploser.": '{0} > {1}*BOOM*{2} Your gun just exploded.',
    '{0} > {1}*CLAC CLAC*{2} Tu recharges. | Mun. : {3} | Charg. : {4}{5}': '{0} > {1}*CLACK CLACK*{2} You reload. | Ammo: {3} | Clips: {4}{5}',
    '{0} > {1}*CLAC*{2} ARME ENRAYÉE': '{0} > {1}*CLACK*{2} JAMMED GUN',
    '{0} > {1}*CLIC*{2} CHARGEUR VIDE': '{0} > {1}*CLICK*{2} EMPTY MAGAZINE',
    '{0} > {1}*CLIC*{2} Gâchette verrouillée.': '{0} > {1}*CLICK*{2} Trigger locked.',
    '{0} > {1}*Crr..CLIC*{2} Tu décoinces ton arme.': '{0} > {1}*Crr..CLICK*{2} You unjam your gun.',
    '{0} > {1}[ARME CONFISQUÉE]{2}': '{0} > {1}[GUN CONFISCATED]{2}',
    '{0} > {1}[Butin]{2} {3} | lettres : {4}{5}': '{0} > {1}[Loot]{2} {3} | letters: {4}{5}',
    (
        '{0} > {1}[DUCK HUNT]{2} Collection complète : lot aléatoire, bon de 50 xp et munitions '
        'réapprovisionnées.{3}'
    ): '{0} > {1}[DUCK HUNT]{2} Collection complete: random reward, 50 xp voucher and replenished ammo.{3}',
    "{0} > {1}[Palier]{2} Bon d'achat : {3} xp.": '{0} > {1}[Milestone]{2} Voucher: {3} xp.',
    '{0} util.': '{0} uses',
    '{0} {1} de pain sur {2}{3}{4}': '{0} {1} of bread on {2}{3}{4}',
    "{0}*BANG* xO'{1}     {2} vient de se faire descendre accidentellement par {3}.": "{0}*BANG* xO'{1}     {2} has just been accidentally shot by {3}.",
    '{0}*PIEWWW*{1}     une balle de {2} ricoche sur {3} grâce à son modificateur de déflexion de {4}%.': "{0}*PEWWW*{1}     {2}'s bullet ricochets off {3}, thanks to a deflection modifier of {4}%.",
    "{0}*PLOC*{1}     l'armure de {2} arrête une balle perdue de {3} grâce à sa protection de {4}%.": "{0}*SHTOK*{1}     {2}'s armor stops a stray bullet from {3}, thanks to its protection of {4}%.",
    '{0}[+{1} événements]{2}': '{0}[+{1} events]{2}',
    '{0}[CANARD MÉCANIQUE]{1} ': '{0}[MECHANICAL DUCK]{1} ',
    '{0}[CANARD MÉCANIQUE]{1} {2}\\_O<{3}   CLIC': '{0}[MECHANICAL DUCK]{1} {2}\\_O<{3}   CLICK',
    '{0}[Classement complet]{1} {2}': '{0}[Full rankings]{1} {2}',
    '{0}[Inventaire]{1} arme: {2}{3} | mun.: {4}/{5} | charg.: {6} | {7} {8} {9}{10} | lettres: {11}': '{0}[Inventory]{1} weapon: {2}{3} | ammo: {4}/{5} | clips: {6} | {7} {8} {9}{10} | letters: {11}',
    (
        '{0}[Profil]{1} {2} xp | niv. {3} ({4}) +{5} xp = niv. sup. | fatigue: {6}{7} | karma: '
        '{8} | rentab.: {9} xp/canard | dépensé: {10} xp  {11}[Stats]{12} préc. théor.: {13} | '
        'effic. tirs: {14}% | fiab. arme: {15}{16}% | armure: {17}% | déflex.: {18}%  '
        '{19}[Arme]{20} enray.: {21} ({22} fois) | confisq.: {23} ({24} fois)'
    ): (
        '{0}[Profile]{1} {2} xp | lv. {3} ({4}) +{5} xp = next lv. | fatigue: {6}{7} | karma: '
        '{8} | profit: {9} xp/duck | spent: {10} xp  {11}[Stats]{12} theor. acc.: {13} | shot '
        'success: {14}% | reliability: {15}{16}% | armor: {17}% | deflect.: {18}%  '
        '{19}[Weapon]{20} jammed: {21} ({22} times) | confisc.: {23} ({24} times)'
    ),
    '{0}[TOP {1}]{2} Aucun chasseur classé.': '{0}[TOP {1}]{2} No ranked hunters.',
    (
        '{0}[Tableau de chasse]{1} meill. tps.: {2} | {3} canards (dont {4} super-canards) | {5} '
        'tirs ratés | {6} tirs à vide | {7} tirs enray. | {8} recharg. compulsifs | {9} tirs '
        'sauvages | {10} accidents | {11} coups tirés  {12}[Accidents]{13} reçu {14} balles '
        'perdues dont {15} mortelles, {16} ont ricoché et {17} ont été encaissées.'
    ): (
        '{0}[Hunting record]{1} best time: {2} | {3} ducks (including {4} golden ducks) | {5} '
        'misses | {6} empty shots | {7} jammed shots | {8} compulsive reloads | {9} wild shots | '
        '{10} accidents | {11} shots fired  {12}[Accidents]{13} received {14} stray bullets '
        'including {15} fatal ones, {16} deflected and {17} absorbed.'
    ),
    '{0}[raté : -{1} xp]{2}': '{0}[missed: -{1} xp]{2}',
    '{0}[tir sauvage : -{1} xp]{2}': '{0}[wild fire: -{1} xp]{2}',
    "{0}·-.,¸¸.-·°'`'°·-.,¸¸.-·°'`'°{1} {2}\\_O<{3}   COIN": "{0}·-.,¸¸.-·°'`'°·-.,¸¸.-·°'`'°{1} {2}\\_O<{3}   QUACK",
    'État': 'Condition',
    'ébloui': 'dazzled',
    'échéances passées du plan actuel.': 'elapsed deadlines in the current plan.',
    'éclateur de canards': 'duck shatterer',
    'écorcheur de canards': 'duck skinner',
    'بطبطة': 'QUACK',
    'Canard': 'Duck',
    'Canards': 'Ducks',
    'Chasse': 'Hunting',
    'Charge': 'Ammunition',
    'Chargeurs': 'Magazines',
    'Munitions': 'Ammunition',
    'can.': 'ducks',
    'niv.': 'lvl.',
    'recharg.': 'reloads',
    'Progression': 'Progress',
    'Confiscations': 'Confiscations',
}
