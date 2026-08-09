# ADR 0013: Provider secrets stay outside configuration storage

Status: Accepted

Decision: persist custom Provider metadata in SQLite and store dynamic API keys only in SessionSecretStore or Windows DPAPI. Default custom Provider and role models feed the existing ModelRouter and OpenAI-compatible gateway.

Consequences: 0..N Providers and automatic model discovery are possible without plaintext credentials. SSRF remains enforced. An unsupported model list does not imply connection failure; manual model input remains available.
