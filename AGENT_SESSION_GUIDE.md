# Agent Session Guide / Агент Session-ийн Гарын Авлага

## English Version

### What is a GitHub Copilot Agent Session?

A GitHub Copilot agent session is an AI-powered coding assistant that helps you work with your codebase. When you start a new agent session, the AI agent:

1. **Analyzes your repository** - Reads and understands your code structure, architecture, and existing patterns
2. **Follows project guidelines** - Adheres to rules defined in `.github/copilot-instructions.md` and `PROJECT_CONTEXT.md`
3. **Makes targeted changes** - Implements features, fixes bugs, and refactors code following best practices
4. **Runs tests and validation** - Ensures changes don't break existing functionality
5. **Documents its work** - Explains what was done and why

### How Agent Sessions Work with JKM Trading AI Bot

This trading bot has specific architectural rules that agents must follow:

#### **Core Architecture Principles**

1. **Indicator-Free Design**
   - ❌ NO traditional indicators: RSI, MACD, Moving Averages, ATR, Bollinger Bands, Ichimoku, VWAP
   - ✅ YES price action: Structure, geometry, swings, fractals, S/R zones, patterns, Fibonacci levels

2. **Component Separation**
   - `market_data_cache.py` - Thread-safe M5 candle storage with resampling cache
   - `core/primitives.py` - Pure indicator-free primitives (structure, swings, zones)
   - `core/user_core_engine.py` - Scan pipelines (deterministic, no I/O)
   - `engines/detectors/` - Plugin-based pattern detectors
   - `scanner_service.py` - Orchestration loop
   - `services/notifier_telegram.py` - Telegram notifications (thin layer)

3. **Detector Contract**
   - Every detector returns a `DetectorResult` with:
     - `match: bool` - Whether pattern detected
     - `direction: Optional["BUY"|"SELL"]` - Trade direction
     - `confidence: float` - Confidence level (0..1)
     - `setup_name: str` - Detector name
     - `evidence: List[str]` - Explanation for users

### Working with Agents on This Project

#### **When to Use an Agent Session**

Use agent sessions for:
- Adding new indicator-free detectors
- Refactoring engine logic
- Improving cache performance
- Adding tests
- Fixing bugs
- Updating documentation

#### **How to Communicate with the Agent**

1. **Be specific about your needs**
   ```
   Good: "Add a head-and-shoulders pattern detector using swing highs/lows"
   Bad: "Add pattern detection"
   ```

2. **Reference existing patterns**
   ```
   "Create a double-bottom detector similar to the existing swing detector in engines/detectors/"
   ```

3. **Specify constraints**
   ```
   "Add support for 1H timeframe resampling without using any moving averages"
   ```

4. **Request validation**
   ```
   "Add tests to verify the new detector works on historical data"
   ```

#### **What Agents Can Do**

✅ Agents can:
- Read and understand your entire codebase
- Create new files and modules
- Edit existing code following your style
- Run tests and linters
- Install dependencies (if needed)
- Commit changes incrementally
- Explain their reasoning

❌ Agents cannot:
- Push directly to protected branches
- Merge pull requests
- Access external systems (databases, APIs) without credentials
- Modify `.github/agents/` directory
- Violate security or copyright rules

#### **Best Practices**

1. **Start with exploration**
   - Let the agent understand your codebase first
   - Point to relevant files: "Check user_core_engine.py for examples"

2. **Incremental changes**
   - Request one feature at a time
   - Verify each change before moving forward
   - Use "show me the diff" to review changes

3. **Leverage existing tests**
   - Ask: "Run the existing tests first to check baseline"
   - Add: "Create tests for the new detector"

4. **Follow the indicator-free rule**
   - Always emphasize: "Use only price structure, no indicators"
   - Reference: "Follow the rules in PROJECT_CONTEXT.md"

### Common Agent Session Tasks

#### **Task 1: Adding a New Detector**

```
User: "Add a triple-top reversal pattern detector that:
- Uses swing highs from primitives
- Detects 3 similar highs within 5% price range
- Returns BUY direction (reversal to downside)
- Includes evidence like 'Three tops at $X with avg spacing Y bars'
- Add tests with sample candle data"
```

Agent will:
1. Read existing detectors in `engines/detectors/`
2. Create new detector file following the pattern
3. Register detector in appropriate registry
4. Add test cases in `tests/`
5. Run tests and verify
6. Commit changes

#### **Task 2: Optimizing Cache Performance**

```
User: "Profile the MarketDataCache resampling and optimize the caching strategy 
for frequently accessed timeframes without changing the API"
```

Agent will:
1. Analyze `market_data_cache.py` and `resample_5m.py`
2. Add profiling code
3. Identify bottlenecks
4. Implement optimizations
5. Verify performance improvement
6. Document changes

#### **Task 3: Adding Timeframe Support**

```
User: "Add support for 4H timeframe resampling while maintaining compatibility 
with existing M5/M15/H1 timeframes"
```

Agent will:
1. Check current resampling logic
2. Add 4H case to resample logic
3. Update tests
4. Verify cache works with new timeframe
5. Update documentation

### Debugging Agent Issues

If an agent seems stuck or makes mistakes:

1. **Clarify the requirement**
   ```
   "Let me clarify: I want X, not Y. The constraint is Z."
   ```

2. **Point to examples**
   ```
   "Look at engines/detectors/swing_detector.py for the pattern to follow"
   ```

3. **Break down the task**
   ```
   "First, just create the detector structure. Don't add tests yet."
   ```

4. **Review and iterate**
   ```
   "The implementation uses MACD which violates the indicator-free rule. 
   Please rewrite using only swing highs/lows."
   ```

### File Structure Reference

```
JKM-AI-BOT/
├── .github/
│   └── copilot-instructions.md     # Agent behavior rules
├── core/
│   ├── primitives.py               # Indicator-free primitives
│   └── user_core_engine.py         # Pure scan engine
├── engines/
│   └── detectors/                  # Plugin detectors
├── market_data_cache.py            # Thread-safe cache
├── resample_5m.py                  # Timeframe resampling
├── scanner_service.py              # Orchestration
├── services/
│   └── notifier_telegram.py        # Notifications
├── tests/                          # Test suite
├── PROJECT_CONTEXT.md              # Architecture overview
└── README.md                       # Setup guide
```

### Key Configuration Files

- `.env` - Environment variables (not committed)
- `user_profiles.json` - User settings (not committed)
- `allowed_users.json` - Access control (not committed)
- `instruments.json` - Trading instruments (not committed)
- `requirements.txt` - Python dependencies
- `pytest.ini` - Test configuration

---

## Монгол хувилбар (Mongolian Version)

### GitHub Copilot Agent Session гэж юу вэ?

GitHub Copilot агент session нь таны кодтой ажиллахад тусалдаг хиймэл оюун ухаантай туслах юм. Шинэ агент session эхлэхэд AI агент:

1. **Таны репозиторийг шинжилнэ** - Кодын бүтэц, архитектур, хэв маягийг ойлгоно
2. **Төслийн удирдамжийг дагана** - `.github/copilot-instructions.md` болон `PROJECT_CONTEXT.md` дотор тодорхойлсон дүрмүүдийг баримтална
3. **Зорилтот өөрчлөлт хийнэ** - Шинэ функц нэмэх, алдаа засах, кодыг сайжруулах
4. **Тест ба баталгаажуулалт хийнэ** - Өөрчлөлт одоо байгаа кодыг эвдэхгүй байгааг шалгана
5. **Ажлаа баримтжуулна** - Юу хийсэн, яагаад хийсэн талаар тайлбарлана

### JKM Trading AI Bot-той агент session хэрхэн ажилладаг

Энэ арилжааны бот агентууд дагах ёстой тодорхой архитектурын дүрэмтэй:

#### **Үндсэн Архитектурын Зарчмууд**

1. **Индикаторгүй Дизайн**
   - ❌ ҮГҮЙ уламжлалт индикаторууд: RSI, MACD, Хөдөлгөөнт дундаж, ATR, Bollinger Bands, Ichimoku, VWAP
   - ✅ ТИЙМ үнийн үйлдэл: Бүтэц, геометр, хэлбэлзэл, фрактал, дэмжлэг/эсэргүүцэл бүс, хэв маяг, Фибоначчи түвшин

2. **Модулийн Тусгаарлалт**
   - `market_data_cache.py` - Thread-safe M5 лаа хадгалалт + resample cache
   - `core/primitives.py` - Индикаторгүй primitive функцүүд
   - `core/user_core_engine.py` - Скан pipeline (deterministic, I/O үгүй)
   - `engines/detectors/` - Plugin detector модулууд
   - `scanner_service.py` - Зохион байгуулалтын цогц
   - `services/notifier_telegram.py` - Telegram мэдэгдэл (нимгэн давхарга)

3. **Detector Гэрээ**
   - Detector бүр `DetectorResult` буцаана:
     - `match: bool` - Хэв маяг олдсон эсэх
     - `direction: Optional["BUY"|"SELL"]` - Арилжааны чиглэл
     - `confidence: float` - Итгэлийн түвшин (0..1)
     - `setup_name: str` - Detector нэр
     - `evidence: List[str]` - Хэрэглэгчид тайлбар

### Энэ төсөл дээр агентуудтай хэрхэн ажиллах

#### **Агент Session хэзээ ашиглах**

Агент session дараах зүйлд ашиглана:
- Шинэ индикаторгүй detector нэмэх
- Engine логикийг сайжруулах
- Cache гүйцэтгэлийг сайжруулах
- Тест нэмэх
- Алдаа засах
- Баримт бичиг шинэчлэх

#### **Агенттай хэрхэн харилцах**

1. **Хэрэгцээгээ тодорхой илэрхийлэх**
   ```
   Сайн: "Swing high/low ашиглан head-and-shoulders pattern detector нэм"
   Муу: "Pattern илрүүлэлт нэм"
   ```

2. **Одоо байгаа жишээ заах**
   ```
   "engines/detectors/ дотор байгаа swing detector-тай төстэй double-bottom detector үүсгэ"
   ```

3. **Хязгаарлалт зааж өгөх**
   ```
   "1H timeframe дэмжлэг нэм, гэхдээ moving average ашиглахгүй"
   ```

4. **Баталгаажуулалт хүсэх**
   ```
   "Шинэ detector түүхэн өгөгдөл дээр ажиллаж байгааг шалгах тест нэм"
   ```

#### **Агент юу хийж чадах**

✅ Агент чадна:
- Бүх кодыг унших, ойлгох
- Шинэ файл, модуль үүсгэх
- Одоо байгаа кодыг засах (таны стайлаар)
- Тест, linter ажиллуулах
- Dependency суулгах (шаардлагатай бол)
- Өөрчлөлтийг commit хийх
- Шалтгаанаа тайлбарлах

❌ Агент чадахгүй:
- Хамгаалагдсан branch руу шууд push хийх
- Pull request merge хийх
- Гаднын систем рүү хандах (нууц үгийг ашиглахгүйгээр)
- `.github/agents/` директорийг өөрчлөх
- Аюулгүй байдал эсвэл зохиогчийн эрхийн дүрэм зөрчих

### Нийтлэг Агент Session Даалгаврууд

#### **Даалгавар 1: Шинэ Detector Нэмэх**

```
Хэрэглэгч: "Triple-top reversal pattern detector нэм:
- Swing high ашигла primitives-аас
- 5% үнийн хязгаарт 3 төстэй high ол
- BUY direction буцаа (доош эргэлт)
- 'Дундаж Y bar зайтай $X дээр гурван орой' гэх мэт нотолгоо оруул
- Жишээ candle өгөгдлөөр тест нэм"
```

#### **Даалгавар 2: Cache Гүйцэтгэлийг Сайжруулах**

```
Хэрэглэгч: "MarketDataCache resampling-ийн гүйцэтгэлийг profile хийж, 
түгээмэл timeframe-ийн cache стратегийг сайжруул. API өөрчлөхгүй."
```

### Түлхүүр Файлууд

- `.env` - Орчны хувьсагчид (commit хийхгүй)
- `user_profiles.json` - Хэрэглэгчийн тохиргоо (commit хийхгүй)
- `allowed_users.json` - Хандалтын хяналт (commit хийхгүй)
- `requirements.txt` - Python dependencies
- `PROJECT_CONTEXT.md` - Архитектурын тойм
- `.github/copilot-instructions.md` - Агентийн зан төлөв

### Санамж

Агент session нь таны хөгжүүлэлтийн хурдыг нэмэгдүүлэх хүчирхэг хэрэгсэл юм. Агентад тодорхой, ойлгомжтой зааварчилгаа өгснөөр та илүү сайн үр дүн авна. Индикаторгүй дизайны зарчмыг мартахгүй!
