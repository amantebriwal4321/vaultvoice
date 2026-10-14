# VaultVoice demo script

About two and a half minutes. Speak it straight through.

This is VaultVoice. It is a privacy first voice vault. I talk, the browser transcribes with the Web Speech API, and one loop decides if I am saving a memory or asking for one.

I will store something sensitive. Call Dr. Mehta about my blood pressure. The clinic number is 415-555-0198.

The router marks that as a store. The privacy guard flags health and a phone number, and it sets the tier to private. The note is embedded on this machine with all MiniLM, then written to Qdrant with the tier, the time, and those PII flags. The raw line stays in my owner list.

Next, a team note. Standup moved to 10:15 in the oak room. Bring the launch checklist. The guard suggests shared, and that is the tier that gets stored.

Now I ask, with the scope set to team: when is standup, and what should I bring?

The router marks a query. Qdrant applies a payload filter for shared and public only. The clinic note is not in the result set. You can still see it on the left, because that list is my vault, but the answer agent never received it. The audit log names the standup chunk and the filter that was applied.

Last check. I switch the scope to me and ask what I said about the clinic. The private note is allowed through the filter, but the phone number and the health detail are redacted before they reach the answer agent. The citation shows the tokens, not the raw line. The audit row is the same chunk the answer used.

That is the product. Voice in, tier on the payload, filter before the model, redaction on the way out of private, and a log of every chunk. If a Lyzr key is set, those three roles run on the Studio inference API. With no key, the booth still runs on a labelled local mock. With no Qdrant URL, it uses the local client.
