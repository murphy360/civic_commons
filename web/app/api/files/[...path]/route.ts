import { NextResponse } from 'next/server';
import { readFile, stat } from 'fs/promises';
import { join } from 'path';
import { existsSync } from 'fs';

export const dynamic = 'force-dynamic';

/**
 * MIME types for common document formats
 */
const MIME_TYPES: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.doc': 'application/msword',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xls': 'application/vnd.ms-excel',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.csv': 'text/csv',
  '.txt': 'text/plain',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
};

/**
 * Get MIME type from file extension
 */
function getMimeType(filePath: string): string {
  const ext = filePath.toLowerCase().match(/\.[^.]+$/)?.[0] || '';
  return MIME_TYPES[ext] || 'application/octet-stream';
}

/**
 * Serve local files from the documents storage directory.
 * 
 * Files are stored at /data/documents/YYYY/MM/filename.ext
 * This route serves them via /api/files/YYYY/MM/filename.ext
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path: pathParts } = await params;
    
    // Validate path parts
    if (!pathParts || pathParts.length === 0) {
      return NextResponse.json(
        { error: 'File path required' },
        { status: 400 }
      );
    }

    // Security: Prevent directory traversal
    const sanitizedParts = pathParts.map(part => {
      // Remove any path traversal attempts
      const sanitized = part.replace(/\.\./g, '').replace(/[<>:"|?*]/g, '');
      if (sanitized !== part) {
        throw new Error('Invalid path characters');
      }
      return sanitized;
    });

    // Build full path - documents are stored in /data/documents
    const baseDir = process.env.DOCUMENT_STORAGE_DIR || '/data/documents';
    const filePath = join(baseDir, ...sanitizedParts);

    // Security: Ensure the path stays within the documents directory
    const normalizedBase = join(baseDir);
    if (!filePath.startsWith(normalizedBase)) {
      return NextResponse.json(
        { error: 'Access denied' },
        { status: 403 }
      );
    }

    // Check if file exists
    if (!existsSync(filePath)) {
      return NextResponse.json(
        { error: 'File not found' },
        { status: 404 }
      );
    }

    // Get file stats
    const stats = await stat(filePath);
    if (!stats.isFile()) {
      return NextResponse.json(
        { error: 'Not a file' },
        { status: 400 }
      );
    }

    // Read file
    const fileBuffer = await readFile(filePath);
    const mimeType = getMimeType(filePath);

    // Extract filename for Content-Disposition
    const filename = sanitizedParts[sanitizedParts.length - 1];

    // Return file with appropriate headers
    return new NextResponse(fileBuffer, {
      status: 200,
      headers: {
        'Content-Type': mimeType,
        'Content-Length': stats.size.toString(),
        'Content-Disposition': `inline; filename="${filename}"`,
        'Cache-Control': 'public, max-age=31536000, immutable', // Cache for 1 year
        'X-Content-Type-Options': 'nosniff',
      },
    });

  } catch (error) {
    console.error('Failed to serve file:', error);
    
    if (error instanceof Error && error.message === 'Invalid path characters') {
      return NextResponse.json(
        { error: 'Invalid file path' },
        { status: 400 }
      );
    }

    return NextResponse.json(
      { error: 'Failed to serve file' },
      { status: 500 }
    );
  }
}
