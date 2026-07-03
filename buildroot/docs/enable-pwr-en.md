``` zsh
# Create overlay directory if needed
sudo mkdir -p /boot/overlay-user

# Create the DTS file
sudo nano /boot/overlay-user/pcie-enable.dts
```

Paste this in the file:
``` zsh
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

Save and compile the file:
``` zsh
sudo dtc -I dts -O dtb -o /boot/overlay-user/pcie-enable.dtbo /boot/overlay-user/pcie-enable.dts
```

Edit Armbian config:
```zsh
sudo nano /boot/armbianEnv.txt
```

Add this line:
```zsh
user_overlays=pcie-enable
```
