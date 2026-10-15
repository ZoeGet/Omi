# Desktop UI dependencies

OmiPet Desktop 0.4 and 0.5 use unmodified installed Python packages. The distribution keeps their license files in the corresponding `.dist-info` directories under `_internal`.

| Component | Version | Upstream / license |
|---|---|---|
| CustomTkinter | 5.2.2 | https://github.com/TomSchimansky/CustomTkinter — MIT |
| darkdetect | 0.8.0 | https://github.com/albertosottile/darkdetect — BSD 3-Clause |
| Pillow | 12.3.0 | https://github.com/python-pillow/Pillow — license text bundled with the package |
| packaging | Installed version recorded in the build environment | https://github.com/pypa/packaging — Apache 2.0 / BSD |

CustomTkinter's bundled Roboto font files originate from Google. Their Apache 2.0 license is included in `licenses/Roboto-LICENSE.txt` (under `_internal` in the frozen application). The application's Chinese UI uses the Windows-installed Microsoft YaHei UI font; OmiPet does not redistribute that font.

References: [CustomTkinter license](https://github.com/TomSchimansky/CustomTkinter/blob/master/LICENSE), [Roboto license](https://github.com/googlefonts/roboto-2/blob/main/LICENSE).
