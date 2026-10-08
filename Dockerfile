FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir strands-decider
# Pre-download the reference checkpoint so the running container is self-contained
RUN python -c "import strands_decider.modeling as m; m.StrandsDeciderModel.load('StrandsAgents/strands-decider-2B-hobson-v21')"
COPY . .
RUN bash scripts/seed_demo_data.sh
EXPOSE 8000
CMD ["bash", "scripts/start_all.sh"]
