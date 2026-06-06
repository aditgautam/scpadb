LATEXMK ?= latexmk
TARGET := main

.PHONY: all clean distclean

all: $(TARGET).pdf

$(TARGET).pdf: $(TARGET).tex references.bib $(wildcard sections/*.tex) acmart.cls ACM-Reference-Format.bst
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error $(TARGET).tex

clean:
	$(LATEXMK) -c $(TARGET).tex

distclean:
	$(LATEXMK) -C $(TARGET).tex
