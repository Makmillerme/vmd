"""
Основні модулі VMD Extractor

ОПТИМІЗАЦІЯ: ExcelExporter НЕ імпортується тут щоб уникнути 
завантаження pandas при старті CLI (~380ms).
Імпортуйте напряму: from vmd_extractor.core.exporter import ExcelExporter
"""

from .orchestrator import VMDOrchestrator
from .downloader import AsyncVMDDownloader
from .processor import AsyncVMDProcessor
from .parser import AsyncVMDParser
from .database import VMDDatabase

# ExcelExporter видалено з lazy import reasons - імпортує pandas (~380ms)
# Використовуйте: from vmd_extractor.core.exporter import ExcelExporter

__all__ = [
    "VMDOrchestrator",
    "AsyncVMDDownloader",
    "AsyncVMDProcessor",
    "AsyncVMDParser",
    "VMDDatabase",
    # "ExcelExporter",  # lazy import - see docstring
]



