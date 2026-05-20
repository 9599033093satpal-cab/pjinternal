#!/usr/bin/env python3
"""
Example Usage Script for OCR Agent
===================================
Demonstrates various ways to use the OCR Agent programmatically
"""

from ocr_agent import OCRAgent
from pathlib import Path
import json


def example_1_basic_usage():
    """Example 1: Basic OCR processing"""
    print("\n" + "="*80)
    print("Example 1: Basic OCR Processing")
    print("="*80)
    
    # Create agent with default settings
    agent = OCRAgent(
        pdf_path="sample.pdf",
        output_dir="results/basic/",
        engine="tesseract",
        language="eng",
        dpi=300,
        num_workers=4,
        split_files=2
    )
    
    # Run OCR
    print("Processing PDF...")
    output_files = agent.run()
    
    print("\nOutput files created:")
    for f in output_files:
        print(f"  ✓ {f}")
    
    # Read and display first few lines of first output file
    with open(output_files[0], 'r') as f:
        lines = f.readlines()
        print("\nFirst 10 lines of output:")
        for line in lines[:10]:
            print(line.rstrip())


def example_2_high_quality():
    """Example 2: High-quality OCR with EasyOCR"""
    print("\n" + "="*80)
    print("Example 2: High-Quality OCR with EasyOCR")
    print("="*80)
    
    agent = OCRAgent(
        pdf_path="complex_document.pdf",
        output_dir="results/high_quality/",
        engine="easyocr",  # Better accuracy
        language="eng",
        dpi=600,  # Higher resolution
        num_workers=8,  # More parallel workers
        split_files=3   # Split into 3 files
    )
    
    output_files = agent.run()
    
    print(f"\nProcessed with high quality settings")
    print(f"Output split into {len(output_files)} files")


def example_3_multi_language():
    """Example 3: Multi-language document (Hindi + English)"""
    print("\n" + "="*80)
    print("Example 3: Multi-language Document Processing")
    print("="*80)
    
    # Note: For actual multi-language, you might need to run twice
    # and combine results, or use PaddleOCR which supports multiple languages
    
    agent = OCRAgent(
        pdf_path="hindi_document.pdf",
        output_dir="results/hindi/",
        engine="tesseract",
        language="hin",  # Hindi
        dpi=300,
        num_workers=4,
        split_files=2
    )
    
    output_files = agent.run()
    print(f"\nHindi OCR completed: {len(output_files)} files")


def example_4_batch_processing():
    """Example 4: Batch process multiple PDFs"""
    print("\n" + "="*80)
    print("Example 4: Batch Processing Multiple PDFs")
    print("="*80)
    
    pdf_files = [
        "document1.pdf",
        "document2.pdf",
        "document3.pdf"
    ]
    
    results = {}
    
    for pdf_file in pdf_files:
        if not Path(pdf_file).exists():
            print(f"Skipping {pdf_file} (not found)")
            continue
        
        print(f"\nProcessing: {pdf_file}")
        
        agent = OCRAgent(
            pdf_path=pdf_file,
            output_dir=f"results/{Path(pdf_file).stem}/",
            engine="tesseract",
            dpi=300,
            num_workers=4,
            split_files=2
        )
        
        output_files = agent.run()
        results[pdf_file] = output_files
    
    # Save batch processing summary
    summary_path = "results/batch_summary.json"
    with open(summary_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nBatch processing complete!")
    print(f"Summary saved to: {summary_path}")


def example_5_custom_processing():
    """Example 5: Custom processing pipeline"""
    print("\n" + "="*80)
    print("Example 5: Custom Processing Pipeline")
    print("="*80)
    
    from ocr_agent import OCRAgent, TesseractEngine
    
    # Create custom OCR engine with specific config
    custom_engine = TesseractEngine(
        language='eng',
        config='--psm 6 --oem 3'  # PSM 6: Assume single uniform block of text
    )
    
    agent = OCRAgent(
        pdf_path="structured_document.pdf",
        output_dir="results/custom/",
        engine="tesseract",
        dpi=300,
        num_workers=4,
        split_files=2
    )
    
    # Override with custom engine
    agent.engine = custom_engine
    
    output_files = agent.run()
    
    # Post-process results
    for output_file in output_files:
        with open(output_file, 'r') as f:
            text = f.read()
        
        # Example: Remove empty lines
        cleaned_lines = [line for line in text.split('\n') if line.strip()]
        cleaned_text = '\n'.join(cleaned_lines)
        
        # Save cleaned version
        cleaned_file = output_file.replace('.txt', '_cleaned.txt')
        with open(cleaned_file, 'w') as f:
            f.write(cleaned_text)
        
        print(f"Created cleaned version: {cleaned_file}")


def example_6_compare_engines():
    """Example 6: Compare different OCR engines"""
    print("\n" + "="*80)
    print("Example 6: Compare OCR Engines")
    print("="*80)
    
    pdf_file = "test_document.pdf"
    
    if not Path(pdf_file).exists():
        print(f"Test file {pdf_file} not found. Skipping comparison.")
        return
    
    engines = ['tesseract', 'easyocr', 'paddleocr']
    results = {}
    
    for engine in engines:
        print(f"\nTesting {engine}...")
        
        try:
            agent = OCRAgent(
                pdf_path=pdf_file,
                output_dir=f"results/comparison/{engine}/",
                engine=engine,
                dpi=300,
                num_workers=4,
                split_files=1  # Single file for comparison
            )
            
            output_files = agent.run()
            
            # Read result
            with open(output_files[0], 'r') as f:
                text = f.read()
            
            results[engine] = {
                'output_file': output_files[0],
                'character_count': len(text),
                'word_count': len(text.split()),
                'line_count': len(text.split('\n'))
            }
            
        except Exception as e:
            print(f"Error with {engine}: {e}")
            results[engine] = {'error': str(e)}
    
    # Print comparison
    print("\n" + "="*80)
    print("OCR Engine Comparison Results:")
    print("="*80)
    
    for engine, stats in results.items():
        print(f"\n{engine.upper()}:")
        if 'error' in stats:
            print(f"  Error: {stats['error']}")
        else:
            print(f"  Characters: {stats['character_count']:,}")
            print(f"  Words: {stats['word_count']:,}")
            print(f"  Lines: {stats['line_count']:,}")
    
    # Save comparison results
    with open("results/comparison/comparison_results.json", 'w') as f:
        json.dump(results, f, indent=2)


def main():
    """Run example demonstrations"""
    print("\n" + "="*80)
    print("OCR Agent - Example Usage Demonstrations")
    print("="*80)
    print("\nThis script demonstrates various ways to use the OCR Agent.")
    print("Make sure you have sample PDF files in the current directory.")
    print("\nExamples available:")
    print("  1. Basic usage")
    print("  2. High-quality OCR with EasyOCR")
    print("  3. Multi-language processing")
    print("  4. Batch processing")
    print("  5. Custom processing pipeline")
    print("  6. Compare OCR engines")
    
    print("\n" + "="*80)
    choice = input("\nEnter example number to run (1-6, or 'all' for all): ")
    
    examples = {
        '1': example_1_basic_usage,
        '2': example_2_high_quality,
        '3': example_3_multi_language,
        '4': example_4_batch_processing,
        '5': example_5_custom_processing,
        '6': example_6_compare_engines
    }
    
    if choice.lower() == 'all':
        for func in examples.values():
            try:
                func()
            except Exception as e:
                print(f"Error in example: {e}")
    elif choice in examples:
        try:
            examples[choice]()
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Invalid choice. Please run again with a valid option.")
    
    print("\n" + "="*80)
    print("Examples completed!")
    print("="*80)


if __name__ == "__main__":
    main()
