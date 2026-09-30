# igit

Zero-Touch-Integration zwischen einer selbst betriebenen Forgejo-Instanz und Claude-Clients: Claude kann mit der Forge arbeiten, ohne dass ein Mensch Schlüssel, Tokens oder Remotes von Hand überträgt.

## Sprache

**Instanz**:
Ein selbst betriebener Forgejo-Server, den der Betreiber für den eigenen Gebrauch betreibt.
_Vermeiden_: Server, Forge (wenn die konkrete Installation gemeint ist)

**Betreiber**:
Der Mensch, der die Instanz betreibt und in dessen Auftrag Claude arbeitet.
_Vermeiden_: Admin, Owner, Nutzer (mehrdeutig mit Forgejo-Konten und Repo-Eigentümern)

**Claude-Client**:
Ein Rechner oder eine Umgebung, in der Claude (z. B. Claude Code) läuft und über Git und die API mit der Instanz spricht.
_Vermeiden_: Agent-Host, Arbeitsplatz

**Bot-Konto**:
Das dedizierte Forgejo-Konto, über das jeder Claude-Client handelt; getrennt vom eigenen Konto des Betreibers, damit Claudes Zugriff eigenständig geprüft und widerrufen werden kann.
_Vermeiden_: Service-Account, Claude-User

**Client-Schlüssel**:
Das SSH-Schlüsselpaar eines Claude-Clients, dessen öffentliche Hälfte am Bot-Konto hinterlegt ist.

**Host-Key-Pinning**:
Das Hinterlegen des SSH-Host-Keys der Instanz auf einem Claude-Client vor der ersten Verbindung, sodass der Client nie einem unverifizierten Host vertraut.
_Vermeiden_: TOFU, known_hosts-Einrichtung

**Registrierung**:
Der Vorgang, durch den ein neuer Claude-Client an einer bestehenden Instanz Client-Schlüssel, Host-Key-Pinning und Token erhält.
_Vermeiden_: Enrollment, Onboarding

**Ersteinrichtung**:
Der Lauf des Skills, der eine Instanz findet oder installiert und Bot-Konto, Client-Schlüssel, Host-Key-Pinning und Token einrichtet. Wiederholte Läufe holen in der UI angelegte Repos per Abgleich nach.
_Vermeiden_: Installation (meint nur das Aufsetzen von Forgejo selbst), Setup

**Projekt**:
Ein Forgejo-Projektboard, das der Betreiber als Board-Ansicht über die Issues eines Repos nutzt; er legt es selbst an, weil Forgejo keine Projekt-API hat.
_Vermeiden_: Projekt im Sinne des Arbeitsverzeichnisses oder des Vorhabens

**Meilenstein**:
Die automatische Gruppierung der Issues eines Repos; der Skill legt ihn an, und Claude ordnet jedes neue Issue ihm zu.

**Zero-Touch**:
Erfordert vom Betreiber keine manuelle Handlung über den Skill-Aufruf, die Rückfragen des Skills und das Anlegen des Projektboards hinaus.

## Beziehungen

- Eine **Instanz** hat genau ein **Bot-Konto**
- Ein **Bot-Konto** hat einen **Client-Schlüssel** pro **Claude-Client**
- Ein Repo hat einen **Meilenstein**, dem jedes von Claude angelegte Issue angehört
- Ein **Projekt** zeigt die Issues eines **Meilensteins** als Board
- Ein **Claude-Client** pinnt den Host-Key jeder **Instanz**, mit der er spricht

## Markierte Mehrdeutigkeiten

- "API-Key" in der ursprünglichen Idee: gemeint ist ein Forgejo-Access-Token des **Bot-Kontos**; ob er sich auf ein Repository beschränken lässt, war offen — Forgejo 16 unterstützt repo-beschränkte Tokens über die API.
