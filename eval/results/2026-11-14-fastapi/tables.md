## Results

Runs: 1080. Errors: 0. Agent cost: $4.07. Judge cost: $2.45.

### All models pooled

| Category | Condition | Runs | Score | Retrieved tokens (med) | Total tokens (med) | Tokens per correct | Found | Turns (med) | Seconds (med) |
|---|---|---|---|---|---|---|---|---|---|
| lookup | C0 none | 54 | 1.00 | 0 | 290 | 335 | 0% | 0 | 3.0 |
| lookup | C1 grep | 54 | 1.00 | 100 | 1,877 | 2,683 | 100% | 1 | 8.1 |
| lookup | C2 graph | 54 | 1.00 | 877 | 7,886 | 8,287 | 100% | 1 | 6.6 |
| lookup | C3 both | 54 | 1.00 | 367 | 6,323 | 6,790 | 100% | 1 | 7.5 |
| callers | C0 none | 54 | 0.39 | 0 | 799 | 2,402 | 0% | 0 | 5.6 |
| callers | C1 grep | 54 | 0.91 | 2,254 | 12,314 | 14,661 | 93% | 3 | 16.4 |
| callers | C2 graph | 54 | 0.69 | 1,311 | 13,202 | 34,409 | 80% | 2 | 13.2 |
| callers | C3 both | 54 | 0.87 | 1,922 | 14,916 | 19,447 | 93% | 2 | 15.2 |
| chain | C0 none | 54 | 0.59 | 0 | 1,304 | 2,090 | 0% | 0 | 6.8 |
| chain | C1 grep | 54 | 0.69 | 3,793 | 12,460 | 26,955 | 100% | 3 | 19.2 |
| chain | C2 graph | 54 | 0.68 | 2,984 | 20,816 | 47,368 | 93% | 3 | 17.7 |
| chain | C3 both | 54 | 0.69 | 3,875 | 20,562 | 40,989 | 100% | 3 | 18.3 |
| ambiguous | C0 none | 54 | 0.83 | 0 | 488 | 747 | 0% | 0 | 4.3 |
| ambiguous | C1 grep | 54 | 0.95 | 1,102 | 5,733 | 8,989 | 85% | 2 | 12.8 |
| ambiguous | C2 graph | 54 | 1.00 | 3,234 | 20,917 | 28,970 | 98% | 3 | 15.7 |
| ambiguous | C3 both | 54 | 0.98 | 1,371 | 13,014 | 15,754 | 83% | 2 | 13.3 |
| explanatory | C0 none | 54 | 0.68 | 0 | 1,234 | 1,962 | – | 0 | 18.5 |
| explanatory | C1 grep | 54 | 0.94 | 3,908 | 21,653 | 30,765 | – | 4 | 36.0 |
| explanatory | C2 graph | 54 | 0.95 | 6,855 | 33,417 | 63,596 | – | 4 | 37.5 |
| explanatory | C3 both | 54 | 0.96 | 4,014 | 29,770 | 45,292 | – | 3 | 34.0 |
| **all** | C0 none | 270 | 0.70 | 0 | 722 | 1,277 | 0% | 0 | 5.6 |
| **all** | C1 grep | 270 | 0.90 | 1,610 | 10,498 | 16,044 | 94% | 2 | 15.9 |
| **all** | C2 graph | 270 | 0.86 | 2,713 | 18,516 | 35,573 | 93% | 3 | 17.0 |
| **all** | C3 both | 270 | 0.90 | 2,011 | 17,188 | 24,640 | 94% | 2 | 15.4 |

### Differences, all models pooled (median-of-medians for tokens, mean for score)

| Category | C3 vs C1 retrieved | C3 vs C1 score | C2 vs C1 retrieved | C2 vs C1 score | C0 score (memory) |
|---|---|---|---|---|---|
| lookup | +267% | +0.00 | +777% | +0.00 | 1.00 |
| callers | -15% | -0.04 | -42% | -0.21 | 0.39 |
| chain | +2% | -0.01 | -21% | -0.02 | 0.59 |
| ambiguous | +24% | +0.03 | +193% | +0.05 | 0.83 |
| explanatory | +3% | +0.03 | +75% | +0.02 | 0.68 |
| **all** | +25% | +0.00 | +68% | -0.03 | 0.70 |

### Pre-registered "best of both" test, per model

Passes only if C3's score ≥ the better of C1 and C2 in **every** category, **and** C3 has the lowest tokens per correct answer of C1–C3.

| Model | lookup | callers | chain | ambiguous | explanatory | Tokens per correct (C1 / C2 / C3) | Result |
|---|---|---|---|---|---|---|---|
| claude-haiku-4.5 | ✅ 1.00 vs 1.00 | ❌ 0.81 vs 0.89 | ❌ 0.69 vs 0.72 | ✅ 1.00 vs 1.00 | ✅ 0.94 vs 0.89 | 14,646 / 28,806 / 23,569 ❌ | **FAIL** |
| claude-haiku-5.5 | ✅ 1.00 vs 1.00 | ❌ 0.89 vs 0.92 | ✅ 0.78 vs 0.75 | ✅ 1.00 vs 1.00 | ❌ 0.94 vs 0.97 | 14,878 / 34,458 / 19,839 ❌ | **FAIL** |
| deepseek-v4.1-flash | ✅ 1.00 vs 1.00 | ✅ 0.92 vs 0.92 | ❌ 0.58 vs 0.61 | ❌ 0.94 vs 1.00 | ✅ 1.00 vs 1.00 | 18,668 / 43,470 / 30,691 ❌ | **FAIL** |

### Per model: claude-haiku-4.5

| Category | Condition | Runs | Score | Retrieved tokens (med) | Total tokens (med) | Tokens per correct | Found | Turns (med) | Seconds (med) |
|---|---|---|---|---|---|---|---|---|---|
| lookup | C0 none | 18 | 1.00 | 0 | 310 | 310 | 0% | 0 | 2.1 |
| lookup | C1 grep | 18 | 1.00 | 18 | 1,824 | 2,467 | 100% | 1 | 6.7 |
| lookup | C2 graph | 18 | 1.00 | 877 | 8,156 | 9,789 | 100% | 1 | 5.4 |
| lookup | C3 both | 18 | 1.00 | 327 | 6,400 | 7,166 | 100% | 1 | 7.4 |
| callers | C0 none | 18 | 0.36 | 0 | 558 | 1,501 | 0% | 0 | 4.7 |
| callers | C1 grep | 18 | 0.89 | 3,802 | 16,620 | 18,863 | 94% | 4 | 18.6 |
| callers | C2 graph | 18 | 0.75 | 1,311 | 13,208 | 19,321 | 83% | 2 | 12.2 |
| callers | C3 both | 18 | 0.81 | 1,700 | 17,586 | 23,160 | 94% | 3 | 14.6 |
| chain | C0 none | 18 | 0.69 | 0 | 749 | 1,058 | 0% | 0 | 4.7 |
| chain | C1 grep | 18 | 0.72 | 3,356 | 11,250 | 22,622 | 100% | 2 | 15.5 |
| chain | C2 graph | 18 | 0.67 | 1,772 | 17,532 | 53,206 | 89% | 3 | 19.1 |
| chain | C3 both | 18 | 0.69 | 2,275 | 20,948 | 47,051 | 100% | 3 | 15.8 |
| ambiguous | C0 none | 18 | 0.83 | 0 | 430 | 539 | 0% | 0 | 3.1 |
| ambiguous | C1 grep | 18 | 0.97 | 898 | 6,102 | 6,838 | 89% | 2 | 13.4 |
| ambiguous | C2 graph | 18 | 1.00 | 2,363 | 14,738 | 23,468 | 100% | 2 | 13.2 |
| ambiguous | C3 both | 18 | 1.00 | 1,538 | 13,678 | 18,153 | 83% | 2 | 12.4 |
| explanatory | C0 none | 18 | 0.83 | 0 | 1,046 | 1,214 | – | 0 | 17.2 |
| explanatory | C1 grep | 18 | 0.86 | 3,298 | 20,249 | 26,561 | – | 4 | 40.3 |
| explanatory | C2 graph | 18 | 0.89 | 4,620 | 23,644 | 45,907 | – | 3 | 37.1 |
| explanatory | C3 both | 18 | 0.94 | 3,410 | 22,403 | 29,755 | – | 3 | 28.5 |
| **all** | C0 none | 90 | 0.74 | 0 | 568 | 819 | 0% | 0 | 4.2 |
| **all** | C1 grep | 90 | 0.89 | 1,834 | 10,956 | 14,646 | 96% | 2 | 14.7 |
| **all** | C2 graph | 90 | 0.86 | 2,190 | 15,242 | 28,806 | 93% | 2 | 13.8 |
| **all** | C3 both | 90 | 0.89 | 1,768 | 16,240 | 23,569 | 94% | 2 | 13.8 |

### Per model: claude-haiku-5.5

| Category | Condition | Runs | Score | Retrieved tokens (med) | Total tokens (med) | Tokens per correct | Found | Turns (med) | Seconds (med) |
|---|---|---|---|---|---|---|---|---|---|
| lookup | C0 none | 18 | 1.00 | 0 | 296 | 361 | 0% | 0 | 3.7 |
| lookup | C1 grep | 18 | 1.00 | 18 | 1,896 | 3,083 | 100% | 1 | 8.5 |
| lookup | C2 graph | 18 | 1.00 | 682 | 7,886 | 8,677 | 100% | 1 | 9.1 |
| lookup | C3 both | 18 | 1.00 | 108 | 6,126 | 7,034 | 100% | 1 | 7.4 |
| callers | C0 none | 18 | 0.47 | 0 | 766 | 1,710 | 0% | 0 | 4.7 |
| callers | C1 grep | 18 | 0.92 | 2,678 | 13,301 | 15,428 | 94% | 3 | 16.0 |
| callers | C2 graph | 18 | 0.64 | 1,080 | 10,728 | 29,128 | 72% | 2 | 15.2 |
| callers | C3 both | 18 | 0.89 | 1,922 | 14,810 | 20,349 | 94% | 2 | 16.3 |
| chain | C0 none | 18 | 0.69 | 0 | 1,304 | 1,761 | 0% | 0 | 7.0 |
| chain | C1 grep | 18 | 0.75 | 3,678 | 17,310 | 28,235 | 100% | 4 | 21.7 |
| chain | C2 graph | 18 | 0.75 | 2,172 | 19,535 | 28,995 | 89% | 3 | 16.8 |
| chain | C3 both | 18 | 0.78 | 2,934 | 20,043 | 26,621 | 100% | 3 | 16.9 |
| ambiguous | C0 none | 18 | 0.86 | 0 | 516 | 761 | 0% | 0 | 4.3 |
| ambiguous | C1 grep | 18 | 1.00 | 1,179 | 6,342 | 7,698 | 89% | 2 | 12.3 |
| ambiguous | C2 graph | 18 | 1.00 | 4,230 | 22,840 | 28,510 | 94% | 3 | 16.1 |
| ambiguous | C3 both | 18 | 1.00 | 1,000 | 12,094 | 12,034 | 89% | 2 | 12.1 |
| explanatory | C0 none | 18 | 0.75 | 0 | 1,217 | 1,874 | – | 0 | 18.3 |
| explanatory | C1 grep | 18 | 0.94 | 2,890 | 19,014 | 23,829 | – | 4 | 35.3 |
| explanatory | C2 graph | 18 | 0.97 | 6,666 | 56,318 | 74,809 | – | 4 | 37.8 |
| explanatory | C3 both | 18 | 0.94 | 3,954 | 29,038 | 35,593 | – | 3 | 31.0 |
| **all** | C0 none | 90 | 0.76 | 0 | 828 | 1,178 | 0% | 0 | 5.8 |
| **all** | C1 grep | 90 | 0.92 | 1,791 | 12,786 | 14,878 | 96% | 3 | 16.2 |
| **all** | C2 graph | 90 | 0.87 | 2,728 | 18,477 | 34,458 | 89% | 2 | 16.8 |
| **all** | C3 both | 90 | 0.92 | 1,466 | 13,362 | 19,839 | 96% | 2 | 15.1 |

### Per model: deepseek-v4.1-flash

| Category | Condition | Runs | Score | Retrieved tokens (med) | Total tokens (med) | Tokens per correct | Found | Turns (med) | Seconds (med) |
|---|---|---|---|---|---|---|---|---|---|
| lookup | C0 none | 18 | 1.00 | 0 | 222 | 334 | 0% | 0 | 2.8 |
| lookup | C1 grep | 18 | 1.00 | 254 | 1,680 | 2,500 | 100% | 1 | 8.2 |
| lookup | C2 graph | 18 | 1.00 | 962 | 5,026 | 6,396 | 100% | 1 | 7.6 |
| lookup | C3 both | 18 | 1.00 | 1,022 | 6,762 | 6,171 | 100% | 2 | 9.1 |
| callers | C0 none | 18 | 0.33 | 0 | 1,718 | 4,357 | 0% | 0 | 8.6 |
| callers | C1 grep | 18 | 0.92 | 1,919 | 5,616 | 9,818 | 89% | 3 | 15.5 |
| callers | C2 graph | 18 | 0.69 | 3,858 | 16,377 | 55,563 | 83% | 3 | 13.9 |
| callers | C3 both | 18 | 0.92 | 2,018 | 11,972 | 15,310 | 89% | 2 | 15.2 |
| chain | C0 none | 18 | 0.39 | 0 | 1,859 | 4,520 | 0% | 0 | 10.5 |
| chain | C1 grep | 18 | 0.61 | 4,740 | 14,147 | 30,504 | 100% | 4 | 19.9 |
| chain | C2 graph | 18 | 0.61 | 6,106 | 28,426 | 63,546 | 100% | 5 | 23.4 |
| chain | C3 both | 18 | 0.58 | 5,290 | 23,556 | 52,930 | 100% | 5 | 27.4 |
| ambiguous | C0 none | 18 | 0.81 | 0 | 600 | 948 | 0% | 0 | 4.7 |
| ambiguous | C1 grep | 18 | 0.89 | 2,106 | 6,270 | 12,794 | 78% | 2 | 12.8 |
| ambiguous | C2 graph | 18 | 1.00 | 3,760 | 14,378 | 34,930 | 100% | 2 | 15.8 |
| ambiguous | C3 both | 18 | 0.94 | 1,394 | 8,762 | 17,152 | 78% | 2 | 14.8 |
| explanatory | C0 none | 18 | 0.44 | 0 | 1,578 | 3,510 | – | 0 | 21.0 |
| explanatory | C1 grep | 18 | 1.00 | 6,430 | 33,471 | 40,935 | – | 6 | 35.4 |
| explanatory | C2 graph | 18 | 1.00 | 10,560 | 49,872 | 68,418 | – | 6 | 40.6 |
| explanatory | C3 both | 18 | 1.00 | 7,594 | 65,416 | 69,127 | – | 8 | 52.0 |
| **all** | C0 none | 90 | 0.59 | 0 | 1,074 | 1,974 | 0% | 0 | 7.3 |
| **all** | C1 grep | 90 | 0.88 | 2,814 | 8,806 | 18,668 | 92% | 3 | 16.7 |
| **all** | C2 graph | 90 | 0.86 | 4,592 | 22,338 | 43,470 | 96% | 4 | 16.3 |
| **all** | C3 both | 90 | 0.89 | 2,164 | 14,705 | 30,691 | 92% | 3 | 16.6 |

### Retrieved tokens by tool (all models)

| Condition | Tool | Calls | Tokens | Tokens per call |
|---|---|---|---|---|
| C1 grep | `read_file` | 699 | 489,059 | 699 |
| C1 grep | `grep` | 592 | 223,299 | 377 |
| C1 grep | `glob` | 39 | 3,963 | 101 |
| C2 graph | `read_code` | 669 | 569,777 | 851 |
| C2 graph | `query_graph` | 177 | 288,228 | 1,628 |
| C2 graph | `semantic_search` | 350 | 150,123 | 428 |
| C2 graph | `get_neighbors` | 181 | 47,965 | 265 |
| C2 graph | `affected` | 26 | 31,320 | 1,204 |
| C2 graph | `explain` | 39 | 12,232 | 313 |
| C2 graph | `get_node` | 69 | 7,685 | 111 |
| C2 graph | `god_nodes` | 6 | 1,446 | 241 |
| C2 graph | `shortest_path` | 39 | 1,298 | 33 |
| C2 graph | `get_community` | 1 | 665 | 665 |
| C2 graph | `graph_stats` | 1 | 89 | 89 |
| C3 both | `read_code` | 479 | 377,097 | 787 |
| C3 both | `grep` | 516 | 163,006 | 315 |
| C3 both | `read_file` | 175 | 122,345 | 699 |
| C3 both | `semantic_search` | 80 | 37,758 | 471 |
| C3 both | `query_graph` | 11 | 10,846 | 986 |
| C3 both | `get_neighbors` | 24 | 5,406 | 225 |
| C3 both | `glob` | 18 | 1,621 | 90 |
| C3 both | `get_node` | 14 | 908 | 64 |
| C3 both | `explain` | 7 | 879 | 125 |
| C3 both | `shortest_path` | 14 | 410 | 29 |
| C3 both | `affected` | 2 | 160 | 80 |
| C3 both | `graph_stats` | 1 | 89 | 89 |

### Reliability and diagnostics

| Condition | Errors | Empty answers | Turn-cap hits | Found but not correct | Correct but key not retrieved | Agent cost (USD) |
|---|---|---|---|---|---|---|
| C0 none | 0 | 19 | 0 | 0 | 120 | 0.20 |
| C1 grep | 0 | 0 | 0 | 43 | 9 | 1.00 |
| C2 graph | 0 | 0 | 5 | 49 | 3 | 1.46 |
| C3 both | 0 | 0 | 1 | 44 | 8 | 1.41 |

### Per question (all models; score mean / retrieved median)

| Question | Category | C0 | C1 | C2 | C3 |
|---|---|---|---|---|---|
| fb-01 | lookup | 1.00 / 0 | 1.00 / 19 | 1.00 / 708 | 1.00 / 57 |
| fb-02 | lookup | 1.00 / 0 | 1.00 / 181 | 1.00 / 3,340 | 1.00 / 358 |
| fb-03 | lookup | 1.00 / 0 | 1.00 / 650 | 1.00 / 2,856 | 1.00 / 929 |
| fb-13 | lookup | 1.00 / 0 | 1.00 / 15 | 1.00 / 604 | 1.00 / 376 |
| fb-14 | lookup | 1.00 / 0 | 1.00 / 469 | 1.00 / 944 | 1.00 / 36 |
| fb-15 | lookup | 1.00 / 0 | 1.00 / 15 | 1.00 / 810 | 1.00 / 527 |
| fb-04 | callers | 0.44 / 0 | 1.00 / 4,415 | 0.28 / 1,591 | 0.83 / 3,725 |
| fb-06 | callers | 0.00 / 0 | 1.00 / 1,331 | 0.61 / 584 | 1.00 / 460 |
| fb-10 | callers | 0.89 / 0 | 0.83 / 2,980 | 1.00 / 1,031 | 0.83 / 2,716 |
| fb-16 | callers | 0.50 / 0 | 1.00 / 1,528 | 0.89 / 3,555 | 1.00 / 575 |
| fb-17 | callers | 0.00 / 0 | 1.00 / 4,877 | 0.89 / 429 | 0.89 / 2,264 |
| fb-18 | callers | 0.50 / 0 | 0.61 / 868 | 0.50 / 2,485 | 0.67 / 1,579 |
| fb-05 | chain | 0.94 / 0 | 0.94 / 2,227 | 1.00 / 4,878 | 1.00 / 2,305 |
| fb-07 | chain | 0.44 / 0 | 0.50 / 5,593 | 0.50 / 6,527 | 0.50 / 5,009 |
| fb-19 | chain | 0.89 / 0 | 0.78 / 1,693 | 0.56 / 2,569 | 0.78 / 1,802 |
| fb-20 | chain | 0.56 / 0 | 0.94 / 3,783 | 0.89 / 1,692 | 0.78 / 3,700 |
| fb-21 | chain | 0.39 / 0 | 0.50 / 3,803 | 0.50 / 1,159 | 0.50 / 4,136 |
| fb-22 | chain | 0.33 / 0 | 0.50 / 4,127 | 0.61 / 3,399 | 0.56 / 4,050 |
| fb-08 | ambiguous | 1.00 / 0 | 1.00 / 335 | 1.00 / 2,708 | 1.00 / 418 |
| fb-09 | ambiguous | 0.50 / 0 | 1.00 / 3,410 | 1.00 / 3,759 | 1.00 / 3,405 |
| fb-23 | ambiguous | 0.50 / 0 | 1.00 / 813 | 1.00 / 2,699 | 1.00 / 826 |
| fb-24 | ambiguous | 1.00 / 0 | 1.00 / 1,291 | 1.00 / 5,003 | 1.00 / 1,436 |
| fb-25 | ambiguous | 1.00 / 0 | 0.78 / 967 | 1.00 / 1,973 | 0.89 / 2,220 |
| fb-26 | ambiguous | 1.00 / 0 | 0.94 / 1,238 | 1.00 / 4,237 | 1.00 / 1,306 |
| fb-11 | explanatory | 0.67 / 0 | 0.89 / 3,655 | 0.89 / 4,758 | 0.89 / 4,665 |
| fb-12 | explanatory | 0.78 / 0 | 1.00 / 6,727 | 0.89 / 10,129 | 1.00 / 7,865 |
| fb-27 | explanatory | 0.72 / 0 | 1.00 / 4,400 | 1.00 / 4,966 | 1.00 / 4,807 |
| fb-28 | explanatory | 0.00 / 0 | 0.78 / 4,160 | 1.00 / 8,744 | 0.94 / 3,364 |
| fb-29 | explanatory | 1.00 / 0 | 1.00 / 2,940 | 0.94 / 11,705 | 1.00 / 2,902 |
| fb-30 | explanatory | 0.89 / 0 | 0.94 / 1,424 | 1.00 / 2,718 | 0.94 / 1,592 |
