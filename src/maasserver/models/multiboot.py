"""
Django models for multi-boot deployment layout storage.

Maps to: src/maasserver/models/multiboot.py (NEW)

Relationships
-------------
MultiBootDeployment  (1) ──→ (N) MultiBootOS  (1) ──→ (N) MultiBootPartition
       │
       └── OneToOneField to Node (one machine = one deployment)
"""

__all__ = [
    "MultiBootDeployment",
    "MultiBootOS",
    "MultiBootPartition",
]

from django.db import models


class MultiBootDeployment(models.Model):
    """Top-level multi-boot configuration for a single machine.

    One ``MultiBootDeployment`` exists per machine that has a multi-boot
    layout configured.  It stores the global boot menu settings and owns
    the list of operating systems (``MultiBootOS``) via a foreign key
    relationship.

    Deleting a deployment cascades to all related ``MultiBootOS`` and
    ``MultiBootPartition`` rows.
    """

    node = models.OneToOneField(
        "Node",
        on_delete=models.CASCADE,
        primary_key=False,  # Django auto-adds id; node is just a FK
        related_name="multi_boot_deployment",
        help_text="The machine this deployment belongs to. One-to-one.",
    )
    default_os_index = models.IntegerField(
        default=0,
        help_text="Index (by priority order) of the OS that boots by default.",
    )
    boot_timeout = models.IntegerField(
        default=5,
        help_text="GRUB menu timeout in seconds before booting the default OS.",
    )
    created = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when this deployment was first created.",
    )
    updated = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when this deployment was last modified.",
    )

    class Meta:
        db_table = "maasserver_multibootdeployment"
        verbose_name = "multi-boot deployment"
        verbose_name_plural = "multi-boot deployments"

    def __str__(self):
        return f"MultiBootDeployment(node={self.node_id}, default={self.default_os_index})"


class MultiBootOS(models.Model):
    """An operating system entry within a multi-boot deployment.

    Each ``MultiBootOS`` represents one OS that will be installed on
    the machine: its OS type (e.g. "ubuntu", "centos", "windows"),
    distro series, kernel, architecture, target disk, and partition
    layout.

    The ``priority`` field determines the order in the GRUB boot menu
    (lower = higher in the list).  The OS with priority 0 corresponds
    to ``MultiBootDeployment.default_os_index``.
    """

    deployment = models.ForeignKey(
        MultiBootDeployment,
        on_delete=models.CASCADE,
        related_name="oses",
        help_text="Parent deployment this OS entry belongs to.",
    )
    osystem = models.CharField(
        max_length=31,
        help_text="Operating system type, e.g. 'ubuntu', 'centos', 'windows'.",
    )
    distro_series = models.CharField(
        max_length=31,
        help_text="Distribution series, e.g. 'jammy', 'noble', 'win2022'.",
    )
    hwe_kernel = models.CharField(
        max_length=31,
        blank=True,
        help_text="HWE kernel flavor, e.g. 'hwe-22.04'. Optional.",
    )
    architecture = models.CharField(
        max_length=31,
        blank=True,
        help_text="Architecture, e.g. 'amd64/generic'. Optional.",
    )
    boot_disk = models.ForeignKey(
        "PhysicalBlockDevice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Which physical disk this OS installs to. Null = auto-detect.",
    )
    priority = models.IntegerField(
        default=0,
        help_text="Boot menu order (0 = first, highest priority). "
        "Must be unique within a deployment.",
    )

    class Meta:
        db_table = "maasserver_multibootos"
        verbose_name = "multi-boot OS entry"
        verbose_name_plural = "multi-boot OS entries"
        ordering = ["priority"]
        constraints = [
            models.UniqueConstraint(
                fields=["deployment", "priority"],
                name="uq_multibootos_deployment_priority",
            ),
        ]

    def __str__(self):
        return f"MultiBootOS(pk={self.pk}, os={self.osystem}/{self.distro_series}, priority={self.priority})"


class MultiBootPartition(models.Model):
    """A single partition definition within a multi-boot OS entry.

    Describes one partition: its mount point (e.g. ``/``, ``/boot``,
    ``/boot/efi``), size in bytes, and filesystem type.

    The set of partitions for a given ``MultiBootOS`` collectively
    define that OS's disk layout.  At minimum, a root partition (``/``)
    must be specified.
    """

    os_entry = models.ForeignKey(
        MultiBootOS,
        on_delete=models.CASCADE,
        related_name="partitions",
        help_text="Parent OS entry this partition belongs to.",
    )
    mount_point = models.CharField(
        max_length=255,
        help_text="Mount point, e.g. '/', '/boot', '/boot/efi'.",
    )
    size = models.BigIntegerField(
        help_text="Partition size in bytes.",
    )
    fstype = models.CharField(
        max_length=31,
        help_text="Filesystem type, e.g. 'ext4', 'fat32', 'xfs', 'ntfs'.",
    )

    class Meta:
        db_table = "maasserver_multibootpartition"
        verbose_name = "multi-boot partition"
        verbose_name_plural = "multi-boot partitions"
        constraints = [
            models.UniqueConstraint(
                fields=["os_entry", "mount_point"],
                name="uq_multibootpartition_osentry_mountpoint",
            ),
        ]

    def __str__(self):
        return (
            f"MultiBootPartition(pk={self.pk}, mount={self.mount_point}, "
            f"size={self.size}, fstype={self.fstype})"
        )

