CXX      ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Ithird_party

all: build/render

third_party/stb_image.h:
	bash third_party/fetch.sh

build/render: src/render.cpp third_party/stb_image.h
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -rf build

.PHONY: all clean
