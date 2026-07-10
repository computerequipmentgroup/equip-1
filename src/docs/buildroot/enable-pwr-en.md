# Enable PCIe power on ROCK 2F development images

These notes add a user device-tree overlay that drives the PCIe power-enable GPIO as a fixed regulator. Use this on Armbian-style development images when the Firehat PCIe controller is not powered. The Buildroot image uses DTS overlays from `src/buildroot/dts/` instead.

## Create the overlay source

```sh
sudo mkdir -p /boot/overlay-user
sudo nano /boot/overlay-user/pcie-enable.dts
```

Paste:

```dts
/dts-v1/;
/plugin/;

/ {
    compatible = "rockchip,rk3528";

    fragment@0 {
        target-path = "/";
        __overlay__ {
            pcie_en: pcie-en {
                compatible = "regulator-fixed";
                regulator-name = "pcie_en";
                regulator-min-microvolt = <3300000>;
                regulator-max-microvolt = <3300000>;
                gpio = <&gpio1 4 0>;
                enable-active-high;
                regulator-boot-on;
                regulator-always-on;
            };
        };
    };
};
```

## Compile it

```sh
sudo dtc -I dts -O dtb -o /boot/overlay-user/pcie-enable.dtbo /boot/overlay-user/pcie-enable.dts
```

## Enable it

Edit `/boot/armbianEnv.txt`:

```sh
sudo nano /boot/armbianEnv.txt
```

Add or extend this line:

```text
user_overlays=pcie-enable
```

Reboot and verify that the PCIe FireWire controller appears on the bus.
