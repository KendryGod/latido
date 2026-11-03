# BORRADOR - NO PROBADO. No se ha construido nunca con rpmbuild.

Name:           latido
Version:        0.0.1
Release:        1%{?dist}
Summary:        Salud y velocidad de discos

License:        GPL-3.0-or-later
URL:            https://github.com/KendryGod/latido
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  desktop-file-utils
BuildRequires:  appstream

Requires:       smartmontools
Requires:       polkit
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       fio
Requires:       fio-engine-libaio

%description
Latido lee los datos SMART de un disco (solo lectura) y muestra su estado:
bueno, precaucion, malo o desconocido.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files latido
install -Dpm 0755 helper/latido-helper %{buildroot}%{_libexecdir}/latido/latido-helper
install -Dpm 0644 data/io.github.kendrygod.latido.policy %{buildroot}%{_datadir}/polkit-1/actions/io.github.kendrygod.latido.policy
install -Dpm 0644 data/io.github.kendrygod.latido.desktop %{buildroot}%{_datadir}/applications/io.github.kendrygod.latido.desktop
install -Dpm 0644 data/io.github.kendrygod.latido.metainfo.xml %{buildroot}%{_metainfodir}/io.github.kendrygod.latido.metainfo.xml

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.kendrygod.latido.desktop
appstreamcli validate --no-net %{buildroot}%{_metainfodir}/io.github.kendrygod.latido.metainfo.xml

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/latido
%dir %{_libexecdir}/latido
%{_libexecdir}/latido/latido-helper
%{_datadir}/polkit-1/actions/io.github.kendrygod.latido.policy
%{_datadir}/applications/io.github.kendrygod.latido.desktop
%{_metainfodir}/io.github.kendrygod.latido.metainfo.xml

%changelog
* Mon Nov 02 2026 Kendry - 0.0.1-1
- Borrador inicial
