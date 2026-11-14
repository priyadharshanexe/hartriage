import os

from hypothesis import settings

# CI runs thousands of generated cases; local runs stay quick.
settings.register_profile("ci", max_examples=3000, deadline=None)
settings.register_profile("dev", max_examples=300, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
