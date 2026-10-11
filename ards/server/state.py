"""Shared server state: one Ops Brain instance used by the REST API and the HTML registration form."""

from ards.config import settings
from ards.ops import ARDSOpsBrain
from ards.registry import registry
from ards.server.verifier import verifier

ops_brain = ARDSOpsBrain(registry=registry, verifier=verifier, config=settings)
