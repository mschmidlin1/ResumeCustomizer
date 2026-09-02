"""Non-secret Textkernel scoring options.

Credentials stay in Streamlit secrets (``account_id`` / ``service_key``).
Restart Streamlit after changing these.
"""

# US | EU | AU — must match the data center of the Tx Console account.
DATA_CENTER = "US"

# Optional parse add-ons (extra credits). Both default off.
# normalize_skills: SkillsSettings.Normalize + taxonomy V2 (+0.1 per parse)
# normalize_job_titles: ProfessionsSettings.Normalize (+0.2 per parse)
NORMALIZE_SKILLS = False
NORMALIZE_JOB_TITLES = False
