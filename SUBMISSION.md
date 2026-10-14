# VaultVoice

Voice notes with a privacy tier on every memory. You speak in the browser (Web Speech API, audio stays on device). A Lyzr router decides store or query. A privacy guard suggests private, shared, or public and flags PII such as phone, email, health, and money. Notes are embedded locally with all-MiniLM-L6-v2 and stored in Qdrant with tier, timestamp, and PII flags. Questions carry an access scope (me, team, or public). Retrieval uses a Qdrant payload filter so the answer agent cannot see forbidden tiers. Private PII is redacted before it leaves the vault. An audit log lists the exact chunks behind each answer.

Track: Privacy-First Knowledge Systems (Lyzr x Qdrant x Omi).

Without `LYZR_API_KEY` the same three roles run on a labelled local mock. Without `QDRANT_URL` the app uses qdrant-client in local or in memory mode, so the demo still completes.
