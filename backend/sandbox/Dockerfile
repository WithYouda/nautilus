# Context assembled by scripts/build-python-sandbox.py from installed CPython
# and pinned wheels. No host user/config/data directory enters this image.
FROM scratch
COPY root/ /
COPY runner.py /opt/nautilus/runner.py
ENV PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg MPLCONFIGDIR=/work/.matplotlib HOME=/work OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["@@PYTHON@@", "-I", "/opt/nautilus/runner.py"]
