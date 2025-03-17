#!/usr/bin/env bash
# Exit on error
set -e

# Install system dependencies required for some Python packages
apt-get update
apt-get install -y build-essential
