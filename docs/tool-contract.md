# Контракт Tool

Tool — внутренняя операция локальной программы. CLI передаёт команду сервису заданий, тот проверяет её, вызывает нужный Tool и сохраняет состояние Job. HTTP API программы нет. Команды и ответы CLI описаны в `docs/api/cli.schema.json`; внешний HAPI-контракт, используемый Import Tool, приведён ниже.

## Общие правила

- Tool не меняет Job напрямую; состояние меняет сервис заданий после результата Tool.
- `raw_dataset` означает набор, который программа сохранила из INTERMAGNET до запуска собственного Processing Tool. Источник может отдавать разные publication states (`reported`, `adjusted`, `quasi-def`, `definitive`, `best-avail`); эти состояния и cadence записываются как происхождение данных.
- Внешний HAPI status `1200` означает успех. `1201` означает успешный ответ без данных за период. HTTP 4xx / HAPI 14xx означают ошибку запроса или набора; HTTP 5xx / HAPI 15xx — ошибку сервера или upstream.
- Ошибка Tool имеет вид `ToolError { code, message, details? }`. Сообщение безопасно для показа пользователю и не включает секреты или неограниченный сырой ответ.
- CLI-команды импорта и обработки требуют ключ идемпотентности. Повтор с тем же ключом и теми же параметрами возвращает тот же Job; с другими параметрами — `idempotency_conflict`.
- Набор и состояние `Completed` фиксируются согласованно. Нельзя показывать частично записанный набор как готовый.

## Внешний контракт INTERMAGNET HAPI

Import Tool обращается к `https://imag-data.bgs.ac.uk/GIN_V1/hapi`. Это внешний HTTP API; локальная программа не предоставляет этот интерфейс сама. INTERMAGNET сообщает о поддержке HAPI 3.1.

| HAPI endpoint | Метод | Назначение и параметры |
|---|---|---|
| `/capabilities` | GET | Получить версию HAPI и список форматов данных, поддерживаемых сервером |
| `/catalog` | GET | Получить список dataset ID и названий доступных наборов |
| `/info` | GET | Получить метаданные и параметры выбранного набора; обязателен `dataset`, допустим `parameters` |
| `/data` | GET | Получить измерения; обязательны `dataset`, `start`, `stop`; допустимы `parameters`, `format` |

Dataset ID имеет составной вид `IAGACode/DataType/Cadence/Components`: код обсерватории, publication state, cadence и система компонент. HAPI INTERMAGNET предлагает cadence `PT1M` и `PT1S`, а компоненты `xyzf`, `hdzf`, `diff` и `native`. Доступные publication state и dataset ID следует брать из актуального каталога, не составлять вручную без проверки.

Вызовы выполняются GET-запросами. Временной интервал у `data` полуоткрытый: `start` включён, `stop` не включён. Ответ может запрашиваться в формате `csv`, `json` или `binary`, если формат перечислен в ответе `capabilities`. Программа сохраняет выбранный dataset ID, параметры, метаданные `info`, статус HAPI и исходное тело `data`.

| HTTP / HAPI status | Значение для Import Tool |
|---|---|
| `200` / `1200` | Запрос успешен, данные могут быть непустыми |
| `200` / `1201` | Запрос успешен, данных за период нет; создать пустой сырой набор и завершить Job как `Completed` |
| `400` / `1400–1405`, `1408–1413` | Ошибка параметров/диапазона/формата; сопоставить с `intermagnet_request_rejected` |
| `404` / `1406–1407` | Неизвестный dataset или параметр; сопоставить с `dataset_unavailable` |
| `500` / `1500–1501` | Ошибка сервера или upstream; сопоставить с `intermagnet_unavailable` |

Источник описания: [INTERMAGNET HAPI](https://imag-data.bgs.ac.uk/GIN_V1/hapi) и [описание INTERMAGNET Web Services](https://imag-data.bgs.ac.uk/GIN_V1/). Конкретный набор и допустимый формат нужно подтвердить по актуальным ответам сервиса перед реализацией.

## Tool 1 — INTERMAGNET Import Tool

Назначение: найти подходящий dataset в INTERMAGNET HAPI, запросить ряд и сохранить ответ источника локально. Tool не выполняет выбранную пользователем последующую научную обработку.

### Вход

```text
ImportRequest {
  observatory_id: string       // трёхбуквенный IAGA code
  publication_state: string    // adjusted | definitive | quasi-def | reported | best-avail
  cadence: string              // PT1M | PT1S
  components: string           // xyzf | hdzf | diff | native
  start: datetime
  stop: datetime
  idempotency_key: string
}
```

Входные значения используются для выбора `dataset` из HAPI catalog. Затем Tool вызывает `info` и `data` по внешнему контракту выше. Время начала включается в запрос, время окончания не включается. Выходной формат при передаче сырого ответа — один из форматов, которые INTERMAGNET сообщает через `capabilities`.

### Результат

```text
ImportResult {
  job_id: string
  raw_dataset_id: string
  intermagnet_dataset_id: string
  record_count: integer
  retrieved_at: datetime
  source_metadata: object
}
```

`source_metadata` сохраняет HAPI dataset ID, publication state, cadence, components, период запроса, описание параметров и HAPI status. Исходное тело ответа сохраняется так, чтобы его можно было прочитать и повторно передать Processing Tool. Набор с нулём записей при HAPI `1201` считается успешным импортом и завершается `Completed`.

### Ошибки

| Код | Причина | Результат |
|---|---|---|
| `invalid_import_request` | Некорректный период или недопустимые параметры CLI | Job не создаётся |
| `dataset_unavailable` | Набор отсутствует в каталоге или указан неизвестный параметр набора (HAPI 1406/1407) | Job становится `Failed` |
| `intermagnet_request_rejected` | HAPI вернул ошибку параметров/ограничения (HAPI 14xx) | Job становится `Failed`; сырой набор не публикуется |
| `intermagnet_unavailable` | Сетевой тайм-аут или ошибка сервера/upstream (HAPI 15xx) после ограниченных повторов | Job становится `Failed`; сырой набор не публикуется |
| `storage_error` | Не удалось сохранить ответ или метаданные локально | Job не становится `Completed`; частичный набор не публикуется |

## Tool 2 — Processing Tool

Назначение: обработать локально сохранённый сырой набор выбранным методом и сохранить отдельный результат. Метод и параметры выбираются пользователем; контракт не придумывает математический алгоритм.

### Вход

```text
ProcessingRequest {
  raw_dataset_id: string
  method_id: string
  parameters: object
  idempotency_key: string
}
```

### Результат

```text
ProcessingResult {
  job_id: string
  processed_dataset_id: string
  source_raw_dataset_id: string
  method_id: string
  parameters: object
  completed_at: datetime
  record_count: integer
  result_metadata: object
}
```

Исходный набор не изменяется. Повторная обработка создаёт новый Job и новый `processed_dataset_id`, связанный с тем же сырьём.

### Ошибки

| Код | Причина | Результат |
|---|---|---|
| `invalid_processing_request` | Нет метода или некорректны параметры | Job не создаётся |
| `raw_dataset_not_found` | Сырой набор отсутствует в локальной БД | Job не создаётся |
| `method_not_supported` | Метод не реализован/не зарегистрирован | Job не создаётся |
| `processing_input_invalid` | Выбранный метод не может принять данный набор | Job становится `Failed`; результат не публикуется |
| `processing_failed` | Во время вычисления произошла ошибка | Job становится `Failed`; результат не публикуется |
| `storage_error` | Результат не удалось сохранить полностью | Job не становится `Completed` |

## Tool 3 — Local Data Query Tool

Назначение: читать сырые и обработанные наборы из локальной БД. Внешний API не вызывается, обработка не запускается.

### Вход

```text
DatasetQuery {
  dataset_kind: "raw" | "processed"
  dataset_id: string?
  observatory_id: string?
  source_raw_dataset_id: string?
  time_range: { start: datetime, stop: datetime }?
  limit: integer?
  cursor: string?
}
```

### Результат

```text
DatasetPage {
  items: list<DatasetSummary>
  next_cursor: string?
}

DatasetSummary {
  dataset_id: string
  dataset_kind: "raw" | "processed"
  observatory_id: string?
  source_raw_dataset_id: string?
  time_range: object?
  record_count: integer
  created_at: datetime
  provenance: object
}
```

Если задан `dataset_id`, Tool возвращает содержимое конкретного набора и его метаданные; иначе — страницу кратких описаний. Сортировка и предел размера страницы должны быть зафиксированы в реализации.

### Ошибки

| Код | Причина |
|---|---|
| `invalid_query` | Недопустимые фильтры, период, курсор или предел |
| `dataset_not_found` | Запрошенный локальный набор не найден |
| `storage_error` | Локальная БД недоступна или чтение завершилось ошибкой |

## Кто что проверяет

| Уровень | Ответственность |
|---|---|
| CLI и сервис заданий (вызывающая сторона) | Проверяют структуру команды, обязательные поля, формат дат и ключ идемпотентности; создают Job и применяют допустимые переходы |
| INTERMAGNET Import Tool | Сопоставляет параметры с каталогом HAPI, проверяет HAPI status и метаданные, сохраняет внешний ответ и происхождение |
| Processing Tool | Проверяет наличие входа, поддержку метода и его параметров; записывает результат отдельно |
| Local Data Query Tool | Проверяет локальные фильтры и предел страницы; читает только локальную БД |
| Репозиторий | Обеспечивает целостное сохранение в рамках возможностей выбранной БД и сообщает ошибки вызывающей стороне |

Вызывающая сторона проверяет синтаксис до создания Job. Tool повторно проверяет ограничения, зависящие от внешнего каталога, содержимого набора или выбранного метода. Ошибка валидации не должна создавать готовый набор.
