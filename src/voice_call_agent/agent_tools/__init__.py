"""Tools the language model calls, each defined once as a Pydantic model. Phase 2.

Reads go to the scheduling backend; write proposals and their confirmation go to
`write_guards`. Understanding the caller is the model's work: nothing here classifies intents.
"""
