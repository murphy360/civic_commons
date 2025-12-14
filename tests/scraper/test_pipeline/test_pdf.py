"""
Tests for the PDF extraction pipeline.
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestPdfProcessor:
    """Tests for PdfProcessor."""
    
    @pytest.mark.asyncio
    async def test_extract_text_from_pdf(self):
        """Test extracting text from a PDF."""
        from scraper.pipeline.pdf import PdfProcessor
        
        processor = PdfProcessor()
        
        # Mock pymupdf4llm response
        mock_markdown = """
        # City Council Minutes
        
        **Date:** January 15, 2024
        
        ## Attendees
        - Mayor Smith
        - Councilmember Jones
        """
        
        with patch('scraper.pipeline.pdf.pymupdf4llm.to_markdown', return_value=mock_markdown):
            result = await processor.extract_text(b"fake pdf bytes")
            
            assert "City Council Minutes" in result
            assert "January 15, 2024" in result
    
    @pytest.mark.asyncio
    async def test_handles_corrupt_pdf(self):
        """Test handling of corrupt PDF files."""
        from scraper.pipeline.pdf import PdfProcessor
        
        processor = PdfProcessor()
        
        with patch('scraper.pipeline.pdf.pymupdf4llm.to_markdown', side_effect=Exception("Invalid PDF")):
            result = await processor.extract_text(b"not a pdf")
            
            assert result is None or result == ""
    
    @pytest.mark.asyncio
    async def test_download_and_extract(self):
        """Test downloading and extracting a PDF."""
        from scraper.pipeline.pdf import PdfProcessor
        
        processor = PdfProcessor()
        
        mock_pdf_bytes = b"fake pdf content"
        mock_markdown = "Extracted content"
        
        with patch.object(processor, '_download_file', return_value=mock_pdf_bytes):
            with patch.object(processor, 'extract_text', return_value=mock_markdown):
                result = await processor.download_and_extract("https://example.com/doc.pdf")
                
                assert result.success
                assert result.content == mock_markdown
