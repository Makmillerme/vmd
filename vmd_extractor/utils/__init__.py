"""
Утиліти VMD Extractor
"""

from .helpers import clean_num, decode_str, sha256_bytes, normalize_vehicle_type
from .imap_utils import (
    connect_imap,
    format_imap_date,
    build_imap_search_criteria,
    parse_email_date,
    check_is_vmd_attachment
)
from .data_extractor import (
    extract_vehicle_type_from_description,
    extract_from_inv_det,
    parse_tech_from_description
)
from .xml_parser import parse_doc2, parse_date_from_xml
from .pdf_handler import build_pdf_filename, attach_pdf_links

__all__ = [
    # Helpers
    "clean_num",
    "decode_str",
    "sha256_bytes",
    "normalize_vehicle_type",
    # IMAP utils
    "connect_imap",
    "format_imap_date",
    "build_imap_search_criteria",
    "parse_email_date",
    "check_is_vmd_attachment",
    # Data extractor
    "extract_vehicle_type_from_description",
    "extract_from_inv_det",
    "parse_tech_from_description",
    # XML parser
    "parse_doc2",
    "parse_date_from_xml",
    # PDF handler
    "build_pdf_filename",
    "attach_pdf_links",
]

