# Контракт Tool

Tool — внутренняя операция локальной программы.
Вызывающая сторона передаёт запрос Dispatcher,
который находит Tool в Registry, проверяет параметры
и управляет состоянием Job.

Собственный HTTP API программы не предусмотрен.
Целевой контракт CLI описан в `api/cli.schema.json`.

## Общий программный контракт

Реализован в `core/contracts.py`.

```python
class Tool:
    job_kind = None

    def validate(self, parameters):
        ...

    def execute(self, parameters, job_id=None):
        ...
```

Метод `validate()` проверяет параметры операции.
Метод `execute()` выполняет операцию и возвращает
экземпляр ToolResult.

```text
ToolResult {
    data: object
    dataset_id: string?
}
```

Для операций с Job поле dataset_id содержит
идентификатор сохранённого результата.

Для синхронного чтения отдельный Job не требуется.

В текущей реализации Dispatcher возвращает Job
для импорта и обработки, а ToolResult — для чтения.
Дополнительные сведения о сохранённом наборе можно
получить через Query Tool.

## Общие правила

- Tool не изменяет Job напрямую.
- Допустимые переходы проверяются внутри Job.
- Состояние Job изменяет Dispatcher.
- Сырой набор — набор до выполнения собственного
  Processing Tool, независимо от publication state
  источника INTERMAGNET.
- Ошибка Tool представлена DomainError.

```text
ToolError {
    code: string
    message: string
    details: object?
}
```

- Сообщения ошибок предназначены для пользователя
  и не включают секреты или необработанные исключения.
- Импорт и обработка требуют ключ идемпотентности.
- Одинаковый ключ и параметры возвращают прежний Job.
- Тот же ключ с другими параметрами или операцией
  возвращает idempotency_conflict.
- Проверка существующего запроса выполняется
  до повторной валидации Tool.
- Новый Job создаётся только после проверки параметров.
- Набор публикуется только после успешного завершения
  соответствующего Job.

## Внешний контракт INTERMAGNET HAPI

Целевой внешний endpoint:

https://imag-data.bgs.ac.uk/GIN_V1/hapi

В практике 2 зафиксирован HAPI версии 3.1.

| Endpoint | Метод | Назначение |
|---|---|---|
| `/capabilities` | GET | Версия HAPI и доступные форматы |
| `/catalog` | GET | Доступные dataset ID |
| `/info` | GET | Метаданные выбранного dataset |
| `/data` | GET | Получение измерений за период |

Для `/info` обязателен параметр dataset,
дополнительно допускается parameters.

Для `/data` обязательны dataset, start, stop,
дополнительно допускаются parameters и format.

Dataset ID имеет вид:

```text
IAGACode/DataType/Cadence/Components
```

Входные значения:

- publication state: adjusted, definitive,
  quasi-def, reported, best-avail;
- cadence: PT1M, PT1S;
- components: xyzf, hdzf, diff, native.

Доступность конкретного набора должна подтверждаться
актуальным каталогом, а не только составлением ID.

Интервал полуоткрытый: начало включается,
окончание не включается.

Формат ответа выбирается из поддерживаемых форматов,
объявленных через capabilities.

| HTTP / HAPI status | Поведение |
|---|---|
| 200 / 1200 | Успешное получение данных |
| 200 / 1201 | Успешное получение пустого набора |
| 400 / 1400–1405, 1408–1413 | intermagnet_request_rejected |
| 404 / 1406–1407 | dataset_unavailable |
| 500 / 1500–1501 | intermagnet_unavailable |

Источники описания:

- https://imag-data.bgs.ac.uk/GIN_V1/hapi
- https://imag-data.bgs.ac.uk/GIN_V1/

В практике 3 настоящий HTTP-адаптер отсутствует.
Import Tool работает через интерфейс IntermagnetSource
и тестовые ответы HapiResponse.

```text
HapiResponse {
    dataset_id: string
    status: integer
    metadata: object
    body: string
}
```

Текущая реализация обрабатывает JSON-тело ответа.

Проверка доступности dataset через каталог, поддерживаемых
форматов через capabilities, сетевых тайм-аутов
и полноты внешних метаданных относится к дальнейшей
реализации адаптера.

## Tool 1 — INTERMAGNET Import Tool

Имя операции в Registry: `import`.

Тип Job: IMPORT.

### Назначение

Получить геомагнитные измерения через адаптер
INTERMAGNET и сохранить сырой набор без научной обработки.

### Вход

```text
ImportRequest {
    observatory_id: string
    publication_state: string
    cadence: string
    components: string
    start: datetime
    stop: datetime
    idempotency_key: string
}
```

В программном интерфейсе Dispatcher ключ
idempotency_key передаётся отдельным аргументом.

Временной интервал должен быть корректным,
start должен предшествовать stop.

Код обсерватории состоит из трёх заглавных
латинских букв.

Дата и время должны содержать часовой пояс.

### Результат Tool

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

Сохраняются исходное JSON-тело ответа, разобранные записи,
метаданные источника, временной период, cadence,
publication state, components и HAPI status.

HAPI 1201 создаёт пустой сырой набор.

Для временных сетевых ошибок и ошибок доступности
источника допускается не более двух попыток получения
данных. Остальные доменные ошибки не повторяются.

### Ошибки

| Код | Причина | Состояние Job |
|---|---|---|
| invalid_import_request | Неверные параметры или период | Job не создаётся |
| dataset_unavailable | Неизвестный набор или параметр HAPI | Failed |
| intermagnet_request_rejected | Ошибка запроса HAPI | Failed |
| intermagnet_unavailable | Источник недоступен после повторов | Failed |
| intermagnet_invalid_response | Некорректный статус, метаданные или тело ответа | Failed |
| storage_error | Ошибка сохранения | Failed |

В П3 проверяются тип ответа, HAPI status,
наличие базовых метаданных и структура JSON.

Полное сопоставление измерений с метаданными info
будет реализовано при подключении реального источника.

## Tool 2 — Processing Tool

Имя операции в Registry: `process`.

Тип Job: PROCESS.

### Назначение

Обработать существующий сырой набор и сохранить
отдельный обработанный результат.

### Вход

```text
ProcessingRequest {
    raw_dataset_id: string
    method_id: string
    parameters: object
    idempotency_key: string
}
```

Ключ идемпотентности передаётся Dispatcher отдельно.

### Результат Tool

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

Сырой набор не изменяется.

Новый запуск обработки с новым ключом создаёт
отдельный Job и processed_dataset_id.

### Метод практики 3

`count_records` — демонстрационный метод подсчёта
записей сырого набора.

Параметры метода:

```json
{}
```

Пример результата для двух исходных записей:

```json
{
  "records": [
    {
      "source_record_count": 2
    }
  ]
}
```

Результат содержит одну итоговую запись.
Поэтому record_count обработанного набора равен 1.

Пустой сырой набор даёт source_record_count = 0.

Метод предназначен для проверки работы доменного ядра.
Он не является полноценным научным алгоритмом.

### Ошибки

| Код | Причина | Состояние Job |
|---|---|---|
| invalid_processing_request | Некорректные параметры | Job не создаётся |
| raw_dataset_not_found | Сырой набор отсутствует | Job не создаётся |
| method_not_supported | Метод не зарегистрирован | Job не создаётся |
| processing_input_invalid | Некорректное содержимое набора | Failed |
| processing_failed | Ошибка вычисления | Failed |
| storage_error | Ошибка сохранения | Failed |

## Tool 3 — Local Data Query Tool

Имя операции в Registry: `query`.

Тип Job: отсутствует.

### Назначение

Читать сохранённые сырые и обработанные наборы
без обращения к внешнему API и запуска обработки.

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

При запросе по dataset_id возвращается описание
конкретного набора с дополнительным полем content.

При запросе списка поле content не возвращается.

### Правила фильтрации и пагинации

- Размер страницы по умолчанию — 100.
- Допустимый limit — от 1 до 1000.
- Основная сортировка — created_at по убыванию.
- Дополнительная сортировка — dataset_id по возрастанию.
- Фильтр time_range выбирает наборы, периоды которых
  пересекаются с запрошенным интервалом.
- source_raw_dataset_id применяется только
  к обработанным наборам.
- limit и cursor используются только при запросе списка.
- Курсор связан с исходными фильтрами и размером страницы.
- Неизвестный курсор или изменение фильтров
  отклоняются с invalid_query.

На первой странице создаётся снимок результатов.
Появление новых наборов не изменяет этот снимок.

Если следующей страницы нет, next_cursor равен null
во внутреннем программном интерфейсе.

Курсоры существуют в памяти текущего процесса.
Срок жизни и очистка курсоров пока не реализованы.

### Ошибки

| Код | Причина |
|---|---|
| invalid_query | Недопустимые фильтры, период, предел или курсор |
| dataset_not_found | Набор отсутствует или недоступен |
| storage_error | Ошибка хранилища |

## Общие ошибки ядра

| Код | Причина |
|---|---|
| unknown_operation | Операция не зарегистрирована |
| operation_already_registered | Имя операции уже занято |
| invalid_parameters | Некорректная общая структура, ключ или параметры |
| invalid_job_transition | Недопустимый переход Job |
| idempotency_conflict | Ключ использован с другими параметрами |
| job_not_found | Job не найден |
| job_interrupted | Выполнение прервано |
| internal_error | Непредвиденная внутренняя ошибка |

## Кто что проверяет

| Уровень | Ответственность |
|---|---|
| CLI | Разбор внешней команды и преобразование полей |
| Dispatcher | Общая структура запроса, идемпотентность и вызов валидации Tool |
| Import Tool | Параметры импорта и базовая проверка ответа HAPI |
| Processing Tool | Наличие сырого набора, метод и его параметры |
| Query Tool | Фильтры, интервал, предел и курсор |
| Job | Допустимые переходы состояний |
| Repository | Хранение, уникальность ключей и согласованная видимость |

В практике 3 проверка параметров реализована
через методы validate() соответствующих Tool.

Dispatcher вызывает их до создания нового Job.

## Соответствие внутреннего интерфейса и CLI

Внутренний Python-интерфейс использует snake_case.
Целевой внешний JSON-контракт CLI использует camelCase.

Например:

- observatoryId → observatory_id;
- rawDatasetId → raw_dataset_id;
- methodId → method_id;
- datasetKind → dataset_kind;
- idempotencyKey → отдельный аргумент Dispatcher;
- timeRange.start и timeRange.stop → start и stop
  при импорте;
- timeRange → time_range при чтении.

Внешнее значение kind = processing соответствует
внутреннему JobKind.PROCESS со значением process.

Будущий CLI-адаптер должен выполнять это преобразование,
добавлять поле ok и форматировать ответы.

Сам CLI-адаптер на практике 3 не реализован.
