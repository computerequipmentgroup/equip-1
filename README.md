# equip-1

- Part one of computer equipment series
- Records tapeless through digital out onto sd card

# parts

- Raspberry Pi CM4
- FireWire Card
- Custom PCB
- Screen + Buttons
- Printed case
- Ports USB-C and FireWire
- Battery

# questions

- How small can we build this?
- How much computational power do we need? Is a CM4 too much, can we take a smaller/slower computer?
- Does the battery power to outlets at the same time?
- What software do we use? There is this one: [DVGrab](https://github.com/ddennedy/dvgrab)
- How much will the finished device cost?

# compatible cameras

- Sony VX1000
- Sony VX2000
- Sony VX2100

Basically every FireWire out.

# documentation

Download: https://github.com/raspberrypi/usbboot
`brew install libusb`

Change directory to the extracted folder
`make`
`sudo ./rpiboot`

If you get this error:
`main.c:1:10: fatal error: 'libusb.h' file not found`

Install this:
`brew install pkg-config`

Sometimes apple computers can not read the Pi after it got flashed, ignore the message and go on to the Raspberry Pi Imager.

Install Raspberry Pi OS Lite (64-bit)
