# Third-party software and data

Leaflet 1.9.4: https://github.com/Leaflet/Leaflet
Copyright (c) 2010-2023, Vladimir Agafonkin
Copyright (c) 2010-2011, CloudMade

SunCalc 1.9.0: https://github.com/mourner/suncalc
Copyright (c) 2011-2015, Vladimir Agafonkin

Both bundled libraries use the following BSD 2-Clause license:

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

Weather data attribution: NOAA/NWS Aviation Weather Center; NWS MPX radar via
Iowa Environmental Mesonet. Transparent county and state boundary tiles:
https://mesonet.agron.iastate.edu/ogc/


Forecast data: NOAA/NCEP HRRR operational and RRFS operational/parallel GRIB feeds.
https://nomads.ncep.noaa.gov/
https://www.nco.ncep.noaa.gov/pmb/products/hrrr/
https://www.nco.ncep.noaa.gov/pmb/products/rrfs/

GRIB decoding: ECMWF ecCodes (Apache 2.0), installed from PyPI at build time.
https://github.com/ecmwf/eccodes
https://github.com/ecmwf/eccodes-python
