# Official frozen full TeX Live distribution. The upstream image is amd64;
# Docker Desktop can run it through its Linux/amd64 emulation on Apple Silicon.
FROM --platform=linux/amd64 texlive/texlive:TL2025-historic@sha256:7056390eac37715fd3e01875037ceb4016cb17d44c611f7bbbfa7a012007979f
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/texlive/bin \
    && ln -s "$(dirname "$(command -v pdflatex)")" /opt/texlive/bin/current \
    && tlmgr info --only-installed > /opt/texlive/package-manifest.txt
COPY deploy/latex/compile_guest.py /opt/compile_guest.py
ENTRYPOINT ["python3", "-I", "/opt/compile_guest.py"]
