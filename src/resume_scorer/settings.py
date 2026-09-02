"""Non-secret Textkernel scoring options.

Credentials stay in Streamlit secrets (``account_id`` / ``service_key``).
Restart Streamlit after changing these.
"""

# US | EU | AU — must match the data center of the Tx Console account.
DATA_CENTER = "US"

# Skills normalization is required for bimetric scoring on new Tx accounts
# (they default to skills taxonomy V2). Extra +0.1 credit per parse.
NORMALIZE_SKILLS = True

# Optional. Profession taxonomy on recent titles (+0.2 per parse).
NORMALIZE_JOB_TITLES = False
