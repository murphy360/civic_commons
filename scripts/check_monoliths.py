#!/usr/bin/env python3
"""
Monolith Detection Script

Scans the codebase to identify files that may have grown too large
and could benefit from refactoring.

Thresholds:
- WARNING: 300+ lines
- CRITICAL: 500+ lines
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Thresholds
WARNING_LINES = 300
CRITICAL_LINES = 500

# Directories to skip
SKIP_DIRS = {
    'node_modules', '__pycache__', '.git', '.next', 'dist', 'build',
    'venv', '.venv', 'env', '.env', 'migrations', 'coverage'
}

# File extensions to check
CHECK_EXTENSIONS = {'.py', '.ts', '.tsx', '.js', '.jsx'}


@dataclass
class FileStats:
    path: str
    lines: int
    functions: int
    classes: int
    
    @property
    def status(self) -> str:
        if self.lines >= CRITICAL_LINES:
            return "CRITICAL"
        elif self.lines >= WARNING_LINES:
            return "WARNING"
        return "OK"
    
    @property
    def emoji(self) -> str:
        if self.lines >= CRITICAL_LINES:
            return "🔴"
        elif self.lines >= WARNING_LINES:
            return "🟡"
        return "🟢"


def count_python_structures(content: str) -> tuple[int, int]:
    """Count functions and classes in Python code."""
    functions = 0
    classes = 0
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('def ') or stripped.startswith('async def '):
            functions += 1
        elif stripped.startswith('class '):
            classes += 1
    return functions, classes


def count_typescript_structures(content: str) -> tuple[int, int]:
    """Count functions and classes in TypeScript/JavaScript code."""
    functions = 0
    classes = 0
    for line in content.split('\n'):
        stripped = line.strip()
        # Count function declarations
        if ('function ' in stripped or 
            'async function ' in stripped or
            '=>' in stripped and ('const ' in stripped or 'let ' in stripped)):
            functions += 1
        elif stripped.startswith('class '):
            classes += 1
    return functions, classes


def analyze_file(filepath: Path) -> Optional[FileStats]:
    """Analyze a single file for size and complexity."""
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
        lines = len(content.split('\n'))
        
        ext = filepath.suffix.lower()
        if ext == '.py':
            functions, classes = count_python_structures(content)
        elif ext in {'.ts', '.tsx', '.js', '.jsx'}:
            functions, classes = count_typescript_structures(content)
        else:
            functions, classes = 0, 0
        
        return FileStats(
            path=str(filepath),
            lines=lines,
            functions=functions,
            classes=classes
        )
    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        return None


def scan_directory(root: Path) -> list[FileStats]:
    """Recursively scan directory for code files."""
    results = []
    
    for item in root.iterdir():
        if item.name in SKIP_DIRS:
            continue
        
        if item.is_dir():
            results.extend(scan_directory(item))
        elif item.is_file() and item.suffix.lower() in CHECK_EXTENSIONS:
            stats = analyze_file(item)
            if stats:
                results.append(stats)
    
    return results


def print_report(results: list[FileStats], root: Path) -> tuple[int, int]:
    """Print analysis report and return (warnings, criticals) count."""
    # Sort by line count descending
    results.sort(key=lambda x: x.lines, reverse=True)
    
    warnings = [r for r in results if r.status == "WARNING"]
    criticals = [r for r in results if r.status == "CRITICAL"]
    
    print("\n" + "=" * 70)
    print("📊 MONOLITH DETECTION REPORT")
    print("=" * 70)
    print(f"\nScanned: {root}")
    print(f"Total files checked: {len(results)}")
    print(f"Thresholds: WARNING={WARNING_LINES} lines, CRITICAL={CRITICAL_LINES} lines")
    print()
    
    if criticals:
        print("🔴 CRITICAL FILES (500+ lines) - Consider immediate refactoring:")
        print("-" * 70)
        for f in criticals:
            rel_path = os.path.relpath(f.path, root)
            print(f"  {f.emoji} {rel_path}")
            print(f"      Lines: {f.lines:,} | Functions: {f.functions} | Classes: {f.classes}")
        print()
    
    if warnings:
        print("🟡 WARNING FILES (300-499 lines) - Monitor for growth:")
        print("-" * 70)
        for f in warnings:
            rel_path = os.path.relpath(f.path, root)
            print(f"  {f.emoji} {rel_path}")
            print(f"      Lines: {f.lines:,} | Functions: {f.functions} | Classes: {f.classes}")
        print()
    
    if not criticals and not warnings:
        print("✅ No monoliths detected! All files are under 300 lines.")
        print()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  🔴 Critical: {len(criticals)} files")
    print(f"  🟡 Warning:  {len(warnings)} files")
    print(f"  🟢 OK:       {len(results) - len(criticals) - len(warnings)} files")
    print()
    
    # Top 10 largest files
    print("📏 TOP 10 LARGEST FILES:")
    print("-" * 70)
    for i, f in enumerate(results[:10], 1):
        rel_path = os.path.relpath(f.path, root)
        print(f"  {i:2}. {f.emoji} {f.lines:5,} lines - {rel_path}")
    print()
    
    return len(warnings), len(criticals)


def main():
    # Determine root directory
    if len(sys.argv) > 1:
        root = Path(sys.argv[1])
    else:
        # Default to project root (parent of scripts directory)
        root = Path(__file__).parent.parent
    
    if not root.exists():
        print(f"Error: Directory not found: {root}", file=sys.stderr)
        sys.exit(1)
    
    print(f"🔍 Scanning for monoliths in: {root}")
    
    results = scan_directory(root)
    warnings, criticals = print_report(results, root)
    
    # Exit with error code if critical files found
    if criticals > 0:
        sys.exit(2)
    elif warnings > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
