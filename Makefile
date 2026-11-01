# Shortcuts for the attacks (Member 3).
# On this PC GNU Make is called mingw32-make:   mingw32-make help
#
# Results always go to:  results/attacks/<data name>/<attack>/<setting>/
# Each run of an attack first deletes that attack's old folder, so old files never pile up.

PY       := .venv/Scripts/python.exe
DATA_DIR := data/raw
OUT      := results/attacks
ATTACKS  := step drift replay
DATASETS := $(basename $(notdir $(wildcard $(DATA_DIR)/*.csv)))

scenario_step   := scenarios/standard/step_12pct.yaml
scenario_drift  := scenarios/standard/drift_15pct.yaml
scenario_replay := scenarios/standard/replay_7d.yaml

.DEFAULT_GOAL := help
.PHONY: gui assess train-fusion help install list settings data test trust-test pipeline-test l1 l1-gui pipeline-gui attack attack-data attacks-all clean plot check-data check-attack

# layer-1 demo: forged | modified | replay | dropped | silent
L1_ATTACKS := forged modified replay dropped silent

help:
	@echo.
	@echo   mingw32-make install                               create .venv and install the requirements
	@echo   mingw32-make list                                  show the data files and the attacks
	@echo   mingw32-make settings ATTACK=step                  show the setting names of an attack
	@echo   mingw32-make attack DATA=semiarid ATTACK=step      run one attack on one data file
	@echo   mingw32-make attack DATA=semiarid ATTACK=step ONLY=T2M,up,value    only some settings
	@echo   mingw32-make attack-data DATA=semiarid             run the 3 attacks on one data file
	@echo   mingw32-make attacks-all                           run the 3 attacks on every data file
	@echo   mingw32-make plot DATA=semiarid                    plot one example of each attack
	@echo   mingw32-make clean                                 delete all attack results
	@echo   mingw32-make clean DATA=semiarid                   delete the results of one data file
	@echo   mingw32-make clean DATA=semiarid ATTACK=step       delete one attack of one data file
	@echo   mingw32-make data                                  download the 3 test sites from NASA POWER
	@echo   mingw32-make l1                                     send records and watch layer 1 catch every attack
	@echo   mingw32-make l1 ATTACK=replay                      run one layer-1 attack (forged modified replay dropped silent)
	@echo   mingw32-make gui                                   open the control room: assess any data, simulate attacks, run experiments
	@echo   mingw32-make assess FILE=station.csv LAT=32.48 LON=-109.93   run the whole defence on a data file (file mode)
	@echo   mingw32-make train-fusion                          re-train the saved fusion model (about 10 min)
	@echo   mingw32-make l1-gui                                open the clickable layer-1 control panel
	@echo   mingw32-make pipeline-gui                          run the whole chain on real data: data, attack, layer 1, residuals
	@echo   mingw32-make test                                  run the attack tests
	@echo   mingw32-make trust-test                            run the layer-1 (trust) tests
	@echo   mingw32-make pipeline-test                         run the end-to-end pipeline tests
	@echo.

list:
	@echo data files in $(DATA_DIR): $(if $(DATASETS),$(DATASETS),none - run: mingw32-make data)
	@echo attacks: $(ATTACKS)

settings: check-attack
	@$(PY) -m sensorguard.attacks.official --scenario $(scenario_$(ATTACK)) --list $(if $(ONLY),--only $(ONLY))

# create the venv if missing, then install the pinned requirements + the package
install:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install -e .
	@echo installed - try: mingw32-make test

data:
	$(PY) tools/fetch_power.py $(DATA_DIR)

test:
	$(PY) -m pytest tests/test_attacks.py -q

trust-test:
	$(PY) -m pytest tests/test_trust.py -q

pipeline-test:
	$(PY) -m pytest tests/test_pipeline.py -q

# layer-1 pipeline demo: send data, see it accepted, then caught.
#   mingw32-make l1                 honest stream + every attack
#   mingw32-make l1 ATTACK=replay   just one attack
l1:
	$(if $(ATTACK),$(if $(filter $(ATTACK),$(L1_ATTACKS)),,$(error ATTACK=$(ATTACK) unknown - one of: $(L1_ATTACKS))))
	$(PY) -m sensorguard.trust.demo $(if $(ATTACK),--attack $(ATTACK))

# the control room (Tkinter): assess any data file, simulate attacks, run experiments, read configs
gui:
	$(PY) tools/sensorguard_gui.py

# file mode from the command line: mingw32-make assess FILE=station.csv LAT=32.48 LON=-109.93 [OUT=results/assess/x]
assess:
	$(PY) scripts/assess.py $(FILE) --lat $(LAT) --lon $(LON) $(if $(OUT),--out $(OUT))

# the frozen fusion model used on new data (results/models_fusion/fusion.joblib)
train-fusion:
	$(PY) scripts/train_fusion.py

# clickable control panel (Tkinter): send records, click attacks, see verdicts
l1-gui:
	$(PY) tools/l1_gui.py

# the whole chain on real data (Tkinter): data -> attack -> layer 1 -> residuals -> screen
pipeline-gui:
	$(PY) tools/pipeline_gui.py

# --- running attacks ----------------------------------------------------------
# run__<data>__<attack> runs one attack on one data file.
run__%:
	$(PY) -m sensorguard.attacks.official --scenario $(scenario_$(word 2,$(subst __, ,$*))) --input $(DATA_DIR)/$(word 1,$(subst __, ,$*)).csv --out $(OUT)/$(word 1,$(subst __, ,$*))/$(word 2,$(subst __, ,$*)) --clean $(if $(ONLY),--only $(ONLY))

attack: check-data check-attack run__$(DATA)__$(ATTACK)

attack-data: check-data $(addprefix run__$(DATA)__,$(ATTACKS))

attacks-all: $(foreach d,$(DATASETS),$(addprefix run__$(d)__,$(ATTACKS)))

plot: check-data
	$(PY) tools/plot_attacks.py $(DATA) $(OUT)/$(DATA)/plot.png

# --- cleaning -------------------------------------------------------------------
# clean                       -> results/attacks
# clean DATA=x                -> results/attacks/x
# clean DATA=x ATTACK=step    -> results/attacks/x/step
clean:
	$(PY) -c "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True); print('deleted', sys.argv[1])" $(OUT)$(if $(DATA),/$(DATA)$(if $(ATTACK),/$(ATTACK)))

# --- checks ---------------------------------------------------------------------
check-data:
	$(if $(DATA),,$(error give DATA=<name>, one of: $(DATASETS)))
	$(if $(wildcard $(DATA_DIR)/$(DATA).csv),,$(error no file $(DATA_DIR)/$(DATA).csv - available: $(DATASETS)))

check-attack:
	$(if $(filter $(ATTACK),$(ATTACKS)),,$(error give ATTACK=<name>, one of: $(ATTACKS)))
