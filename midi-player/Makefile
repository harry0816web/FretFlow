SWIFTC ?= swiftc
BUILD_DIR := .build
TARGET := $(BUILD_DIR)/midi-player
SOURCE := MidiPlayer.swift

.PHONY: build clean inspect run

build: $(TARGET)

$(TARGET): $(SOURCE)
	mkdir -p $(BUILD_DIR)
	$(SWIFTC) $(SOURCE) -o $(TARGET) -framework AVFoundation -framework AudioToolbox

inspect: build
	@test -n "$(MIDI)" || (echo 'Usage: make inspect MIDI="../basic_pitch_output/file.mid"' && exit 2)
	$(TARGET) "$(MIDI)" --inspect

run: build
	@test -n "$(MIDI)" || (echo 'Usage: make run MIDI="../basic_pitch_output/file.mid"' && exit 2)
	$(TARGET) "$(MIDI)"

clean:
	rm -rf $(BUILD_DIR)
