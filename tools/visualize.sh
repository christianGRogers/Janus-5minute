#!/bin/bash
# Quick visualization script for Janus Bot performance data
# Usage: bash visualize.sh [csv_file] [output_dir]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
CSV_FILE="${1:-}"
OUTPUT_DIR="${2:-./charts}"

# Check if CSV file was provided
if [ -z "$CSV_FILE" ]; then
    echo -e "${RED}❌ Error: CSV file not specified${NC}"
    echo ""
    echo -e "${BLUE}Usage:${NC}"
    echo "  bash visualize.sh <csv_file> [output_dir]"
    echo ""
    echo -e "${BLUE}Examples:${NC}"
    echo "  bash visualize.sh market_performance.csv"
    echo "  bash visualize.sh ../logs/markets/2026-04-23_22-15-45/market_performance.csv"
    echo "  bash visualize.sh market_performance.csv ./my_charts"
    echo ""
    echo -e "${BLUE}Finding recent CSV files:${NC}"
    find ../logs/markets -name "market_performance.csv" -type f 2>/dev/null | head -5
    exit 1
fi

# Check if file exists
if [ ! -f "$CSV_FILE" ]; then
    echo -e "${RED}❌ Error: File not found: $CSV_FILE${NC}"
    exit 1
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Error: Python 3 is not installed${NC}"
    exit 1
fi

# Check if requirements are installed
echo -e "${BLUE}📦 Checking dependencies...${NC}"
python3 -c "import pandas, matplotlib, seaborn" 2>/dev/null || {
    echo -e "${YELLOW}⚠️  Missing dependencies. Installing...${NC}"
    pip install -r requirements-analysis.txt || {
        echo -e "${RED}❌ Failed to install dependencies${NC}"
        exit 1
    }
}

# Run visualization
echo ""
echo -e "${BLUE}📊 Running visualization tool...${NC}"
echo -e "   Input: ${YELLOW}$CSV_FILE${NC}"
echo -e "   Output: ${YELLOW}$OUTPUT_DIR${NC}"
echo ""

python3 visualize_performance.py "$CSV_FILE" --output "$OUTPUT_DIR"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Visualization complete!${NC}"
    echo -e "📁 Charts saved to: ${YELLOW}$(cd "$OUTPUT_DIR" && pwd)${NC}"
    echo ""
    
    # Try to open output directory if possible
    if command -v xdg-open &> /dev/null; then
        xdg-open "$OUTPUT_DIR"
    elif command -v open &> /dev/null; then
        open "$OUTPUT_DIR"
    fi
else
    echo ""
    echo -e "${RED}❌ Visualization failed with exit code $exit_code${NC}"
    exit $exit_code
fi
