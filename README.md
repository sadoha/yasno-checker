# Yasno Power Outage CLI

A command-line interface tool to quickly fetch up-to-date power outage schedules (both stabilization and emergency) directly from the Yasno API. Supports Kyiv and the Kyiv region.

## Prerequisites
- **Python:** 3.10+ (for local execution)
- **Docker:** (optional) for running the pre-built isolated container
- **Git:** for version control

## Running via Virtual Environment (Python)

1. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
2. Run the script:

By address in Kyiv (default city):
```bash
./venv/bin/python3 yasno_check.py --street "Хрещатик" --house "22"
```
By exact group identifier:
```bash
./venv/bin/python3 yasno_check.py --group "19.1"
```    
> [!IMPORTANT]
>**Important Note on Group Codes:** When you pass `--group "19.1"`, the script skips the address resolution step (where the `regionId` is primarily needed) and directly >queries the Yasno API for that group's schedule. Because Yasno returns schedules for all groups at once, the script will find it as long as a group with that name exists in >the response, regardless of the city passed. However, to be absolutely certain (or in case different regions eventually introduce groups with identical names), it is highly >recommended to always pass the `--city` parameter alongside the group.

## Running via Docker Hub (Pre-built Image)

You can run the script securely without installing Python dependencies by using the pre-built Docker image hosted on Docker Hub.

1. Execute a request by address (the container is automatically removed after completion):
```bash
docker run --rm sadoha/yasno-checker:1.0.1 --city "kyiv" --street "Хрещатик" --house "22"
```
2. Execute a request by exact group identifier (safely including the city):
```bash
docker run --rm sadoha/yasno-checker:1.0.1 --city "kyiv" --group "19.1"
```
3. View all available arguments:
```bash
docker run --rm sadoha/yasno-checker:1.0.1 --help
```
## Building the Docker Image Locally (Optional)

If you need to build the image yourself directly from the source code, run the following command in the project directory:
```bash
docker build -t yasno-checker:local .
```
Once the local image is built, you can run it to fetch schedules and get the script's output directly in your terminal, just like the pre-built one:
```bash
docker run --rm yasno-checker:local --city "kyiv" --street "Хрещатик" --house "22"
```
## Architecture & Security
- **Strict DRY & Typing:** 100% compatible with strict typing checks.
- **Container Security:** Runs as a non-root user (10000), read-only root filesystem, all system capabilities dropped.
- **Timezones:** Hardcoded to Europe/Kyiv regardless of the host machine's timezone settings.
