
ty https://github.com/markbirss/rock-2f?tab=readme-ov-file

Compile and install the required spidev and i2c0 overlays:
```
git clone https://github.com/radxa-pkg/radxa-overlays
cd radxa-overlays
make build-dtbo -j$(nproc)

sudo cp ./arch/arm64/boot/dts/rockchip/overlays/rk3528-spi0-cs1-spidev.dtbo /boot/dtb/rockchip/overlay/
sudo cp ./arch/arm64/boot/dts/rockchip/overlays/rk3528-i2c0-m1.dtbo /boot/dtb/rockchip/overlay/
```

Enable the overlays modify /boot/armbianEnv.txt
```
verbosity=1
bootlogo=true
console=both
overlay_prefix=rk35xx
fdtfile=rockchip/rk3528-rock-2f.dtb
rootdev=UUID=6457ccf1-edc1-4c9c-935f-fdb8dc320999
rootfstype=ext4
overlays=rk3528-spi0-cs1-spidev rk3528-i2c0-m1
usbstoragequirks=0x2537:0x1066:u,0x2537:0x1068:u
```

Connect and test i2c
```
sudo i2cdetect -r -y 0
[sudo] password for user: 
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- -- 
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
50: 50 -- -- -- -- -- -- -- 58 -- -- -- -- -- -- -- 
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
70: -- -- -- -- -- -- -- -- 
```

