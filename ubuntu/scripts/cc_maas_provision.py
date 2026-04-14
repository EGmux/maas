"""MAAS VM Provisioning Module

Copies files and provisions VM during cloud-init.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from cloudinit.cloud import Cloud
from cloudinit.config import Config
from cloudinit.config.schema import MetaSchema
from cloudinit.distros import ALL_DISTROS
from cloudinit.settings import PER_INSTANCE

LOG = logging.getLogger(__name__)

meta: MetaSchema = {
    "id": "cc_maas_provision",
    "distros": [ALL_DISTROS],
    "frequency": PER_INSTANCE,
    "activate_by_schema_keys": ["maas_provision"],
}

def handle(name: str, cfg: Config, cloud: Cloud, args: list) -> None:
    LOG.debug(f"Running MAAS provisioning module: {name}")
    
    provision_cfg = cfg.get("maas_provision", {})

    # 1. Inject SSH key
    ssh_config = provision_cfg.get("ssh_key", {})
    if ssh_config:
        _inject_ssh_key(ssh_config)
    
    # 1. Copy files to VM
    copy_files = provision_cfg.get("copy", [])
    for file_spec in copy_files:
        source = file_spec.get("source")
        destination = file_spec.get("destination")
        permissions = file_spec.get("permissions", "0644")
        owner = file_spec.get("owner", "root:root")
        
        if source and destination:
            _copy_file(source, destination, permissions, owner)
            LOG.info(f"Copied {source} -> {destination}")
    
    # 2. Run commands
    run_commands = provision_cfg.get("runcmd", [])
    for cmd in run_commands:
        _run_command(cmd)
        LOG.info(f"Ran command: {cmd}")
    
    # 3. Clone MAAS source (if requested)
    clone_maas = provision_cfg.get("clone_maas", {})
    if clone_maas:
        _clone_maas(clone_maas)
    
    LOG.info("MAAS provisioning complete")

def _inject_ssh_key(config: dict) -> None:
    """Inject SSH public key into authorized_keys."""
    key_name = config.get("name", "id_ed25519")
    key_path = Path("/home/ubuntu/.ssh") / f"{key_name}.pub"
    auth_keys_path = Path("/home/ubuntu/.ssh/authorized_keys")
    
    if not key_path.exists():
        LOG.warning(f"SSH public key not found at {key_path}")
        return
    
    public_key = key_path.read_text().strip()
    public_key_clean = " ".join(public_key.split()[:2])
    
    auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
    
    if auth_keys_path.exists():
        existing = auth_keys_path.read_text()
        if public_key_clean in existing:
            LOG.debug("SSH key already in authorized_keys")
            return
    
    with auth_keys_path.open("a") as f:
        f.write(f"{public_key}\n")
    
    os.chmod(auth_keys_path, 0o600)
    os.chmod(auth_keys_path.parent, 0o700)
    LOG.info(f"Injected SSH key into {auth_keys_path}")

def _copy_file(source: str, dest: str, perms: str, owner: str) -> None:
    """Copy a file from source to destination."""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    if os.path.isfile(source):
        shutil.copy2(source, dest)
    elif os.path.isdir(source):
        shutil.copytree(source, dest, dirs_exist_ok=True)
    
    # Set permissions
    os.chmod(dest, int(perms, 8))
    
    # Set ownership
    user, group = owner.split(':')
    subprocess.run(["chown", f"{user}:{group}", dest], check=False)

def _run_command(cmd) -> None:
    """Run a shell command."""
    if isinstance(cmd, str):
        subprocess.run(cmd, shell=True, check=False)
    elif isinstance(cmd, list):
        subprocess.run(cmd, check=False)

def _clone_maas(config: dict) -> None:
    """Clone MAAS repository."""
    url = config.get("url", "https://github.com/canonical/maas-dev-setup.git")
    branch = config.get("branch", "main")
    dest = Path(config.get("path", "/home/ubuntu/maas-dev-setup"))
    
    if dest.exists():
        LOG.debug(f"MAAS source already exists at {dest}")
        return
    
    LOG.info(f"Cloning MAAS: {url} (branch: {branch})")
    subprocess.run(
        ["git", "clone", "--branch", branch, url, str(dest)],
        check=True
    )
    
    # Fix ownership
    subprocess.run(["chown", "-R", "ubuntu:ubuntu", str(dest)], check=False)
