************************
MAAS: Metal as a Service
************************
Metal as a Service -- MAAS -- lets you treat physical servers like virtual machines in the cloud.
Rather than having to manage each server individually, MAAS turns your bare metal into an elastic
cloud-like resource.

What does that mean in practice? Tell MAAS about the machines you want it to manage and it will
boot them, check the hardware's okay, and have them waiting for when you need them. You can then
pull nodes up, tear them down and redeploy them at will; just as you can with virtual
machines in the cloud.

When you're ready to deploy a service, MAAS gives your tool of choice (e.g. Ansible, Chef, Puppet,
SALT, Juju) the nodes it needs to power that service. It's as simple as that: no need to manually
provision, check and, afterwards, clean-up. As your needs change, you can easily scale services up
or down. Need more power for your Hadoop cluster for a few hours? Simply tear down one of your
Nova compute nodes and redeploy it to Hadoop. When you're done, it's just as easy to give the node
back to Nova.

MAAS is ideal where you want the flexibility of the cloud, and the hassle-free power of Juju
charms, but you need to deploy to bare metal.

For more information see the `MAAS guide`_.

.. _MAAS guide: https://maas.io/


************************
MAAS Multiboot Extension POC
************************

This branch extends MAAS to deploy a single bare-metal machine with
two operating systems side-by-side — fully automated through MAAS.
Define a layout with two OSes (e.g. Ubuntu 22.04 and Ubuntu 24.04),
each with its own partitions, and MAAS partitions the disk, installs
both OSes in sequence, and builds a unified GRUB boot menu to pick
which one to run at power-on.  The architecture supports N OSes in
principle, but the current proof-of-concept covers the dual-boot case.

This turns MAAS from a single-OS provisioner into a platform that
can deliver multiple environments on the same node — useful for
hardware testing, CI fleets, edge gateways, or any scenario needing
OS diversity without dedicating separate machines.

The extension adds four CLI operations (``set-layout``,
``get-layout``, ``delete-layout``, ``multi-boot-deploy``) via a
lightweight mixin that leaves MAAS's existing deploy pipeline
untouched.  Everything — generating per-OS install configs, merging
a unified disk layout, and packaging it into a single self-extracting
installer — happens in one PXE boot cycle.  This is a capstone project at
CIn (Centro de Informática), Universidade Federal de Pernambuco
(UFPE), Brazil.

