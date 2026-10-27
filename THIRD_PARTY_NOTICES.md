# Third-party notices

Vector 1A is an independent streaming implementation informed by and designed
for compatibility with the following MIT-licensed projects.

## funscript-tools

- Source: https://github.com/edger477/funscript-tools
- Parity revision: `7cecc013061f9c4851850fef8f31f7e52d97aa88`
- Copyright (c) 2024 edger477
- License: MIT

## ReStim

- Source: https://github.com/diglet48/restim
- Parity revision: `5c0605304a024208b079d37895ca2ff7f5d54720`
- Copyright (c) 2023 diglet48
- License: MIT

## Senorgif33 restim-vector-live fork

- Source: https://github.com/Senorgif33/restim-vector-live
- Custom-event reference revision: `f3978be94e7cfe0296184f0c9920d0962015d9ec`
- Event definitions include recipe credits recorded in `vector1a/event_definitions.yml`
- License: MIT

The MIT license text applicable to these upstream projects is reproduced below:

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.


## Howl conversion

Electrode panning, FOC constraint projection, amplitude and frequency formulas
are adapted from Howl by Amethyst-Sysadmin: https://github.com/Amethyst-Sysadmin/Howl
Upstream declares original code MIT licensed and prohibits distributing derived
software under the name Howl or a similar name. This application remains Vector 1A.

MIT License

Copyright (c) Amethyst-Sysadmin and Howl contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Alpha81 development acknowledgements

Thanks to Senorgif33 (https://github.com/Senorgif33/restim-vector-live) for the socket-status callback lock-inversion finding and Windows executable distribution example. Alpha81 implements callback deferral on the alpha80 networking baseline and an independent portable executable build.


## Pillow

The curve preview uses Pillow, distributed under the HPND license. Its license is included as PILLOW_LICENSE.txt in the release.
