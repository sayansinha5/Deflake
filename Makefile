.PHONY: keys

# Print a fresh Fernet key for GITHUB_TOKEN_ENCRYPTION_KEY.
keys:
	@python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
