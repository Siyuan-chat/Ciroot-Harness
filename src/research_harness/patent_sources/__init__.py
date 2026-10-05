"""Injected-transport patent source adapters; no adapter owns HTTP sessions."""

from .contracts import SourceContext, SourceFailure
from .jpo import JPOAdapter
from .epo_publication import EPOPublicationAdapter
from .epo_linked import EPOLinkedAdapter
from .uspto import USPTOAdapter
from .pearl import PearlAdapter
from .kipris import KIPRISAdapter
from .tipo import TIPOAdapter
from .gpss import GPSSAdapter

__all__ = ["SourceContext", "SourceFailure", "JPOAdapter", "EPOPublicationAdapter", "EPOLinkedAdapter", "USPTOAdapter", "PearlAdapter", "KIPRISAdapter", "TIPOAdapter", "GPSSAdapter"]
