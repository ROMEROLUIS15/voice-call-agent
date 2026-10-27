"""Practice schedule: an in-memory scheduling backend and business resolver over fictitious
businesses, for development only (manifest §11).

It follows the contract's tenancy: the business of every request comes from the call registered
when its business was resolved, never from the request.
"""
