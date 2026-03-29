source "qemu" "lvm" {
  boot_command    = ["<wait>e<wait5>", "<down><wait><down><wait><down><wait2><end><wait5>", "<bs><bs><bs><bs><wait>autoinstall ipv6.disable=1 ---<wait><f10>"]
  boot_wait       = "2s"
  cpus            = 2
  disk_size       = "8G"
  format          = "raw"
  headless        = var.headless
  http_directory  = var.http_directory
  iso_checksum    = "${lookup(local.iso_checksum, var.architecture, "")}"
  iso_target_path = "packer_cache/${var.ubuntu_series}-${var.architecture}.iso"
  iso_url         = "${lookup(local.iso_url, var.architecture, "")}"
  memory          = 2048
  qemu_binary    = "qemu-system-${lookup(local.qemu_arch, var.architecture, "")}"
  vnc_bind_address = "0.0.0.0"
  qemuargs = [
    ["-machine", "${lookup(local.qemu_machine, var.architecture, "")}"],
    ["-cpu", "${lookup(local.qemu_cpu, var.architecture, "")}"],
    ["-boot", "strict=off"],
    ["-device", "qemu-xhci"],
    ["-device", "usb-kbd"],
    ["-device", "virtio-blk-pci,drive=drive0,bootindex=0"],
    ["-device", "virtio-blk-pci,drive=cdrom0,bootindex=1"],
    ["-device", "virtio-blk-pci,drive=drive1,bootindex=2"],
    ["-device", "virtio-gpu-pci"],
    ["-global", "driver=cfi.pflash01,property=secure,value=off"],
    ["-drive", "if=pflash,format=raw,id=ovmf_code,readonly=on,file=OVMF_CODE.fd"],
    ["-drive", "if=pflash,format=raw,id=ovmf_vars,file=OVMF_VARS.fd"],
    ["-drive", "file=output-lvm/packer-lvm,if=none,id=drive0,cache=writeback,discard=ignore,format=raw"],
    ["-drive", "file=seeds-lvm.iso,format=raw,cache=none,if=none,id=drive1,readonly=on"],
    ["-drive", "file=packer_cache/${var.ubuntu_series}-${var.architecture}.iso,if=none,id=cdrom0,media=cdrom"]
  ]
  shutdown_command       = "sudo -S shutdown -P now"
  ssh_handshake_attempts = 500
  ssh_password           = var.ssh_ubuntu_password
  ssh_timeout            = var.timeout
  ssh_username           = "ubuntu"
  ssh_wait_timeout       = var.timeout
}

build {
  sources = ["source.qemu.lvm"]

  # Copy curtin hooks
  provisioner "file" {
    destination = "/tmp/curtin-hooks"
    source      = "${path.root}/scripts/curtin-hooks"
  }

  # Copy custom cloud-init module (to be installed via shell)
  provisioner "file" {
    source      = "${path.root}/scripts/cc_maas_provision.py"
    destination = "/tmp/cc_maas_provision.py"
  }

  # Copy cloud-init module config
  provisioner "file" {
    source      = "${path.root}/scripts/99_maas_provision.cfg"
    destination = "/tmp/99_maas_provision.cfg"
  }

  # Run all setup scripts
  provisioner "shell" {
    environment_vars = [
      "HOME_DIR=/home/ubuntu",
      "http_proxy=${var.http_proxy}",
      "https_proxy=${var.https_proxy}",
      "no_proxy=${var.no_proxy}"
    ]
    execute_command   = "echo 'ubuntu' | {{ .Vars }} sudo -S -E sh -eux '{{ .Path }}'"
    expect_disconnect = true
    scripts = [
      "${path.root}/scripts/curtin.sh",
      "${path.root}/scripts/networking.sh",
      "${path.root}/scripts/install-module.sh",
    ]
  }

  post-processor "compress" {
    output = "maas-controller-lvm.dd.gz"
  }
}
