from marshmallow import Schema, fields, post_dump


class TemplateFieldSchema(Schema):
    name = fields.Str(required=True)
    label = fields.Str(required=True)
    type = fields.Str(required=True)
    required = fields.Bool()
    hint = fields.Str(allow_none=True)
    options = fields.List(fields.Dict())


class TemplateSchema(Schema):
    id = fields.Int(required=True)
    name = fields.Str(required=True)
    description = fields.Str(allow_none=True)
    layout = fields.Str(required=True)
    fields = fields.List(fields.Nested(TemplateFieldSchema))


class RequestSchema(Schema):
    id = fields.Int(required=True)
    title = fields.Str(required=True)
    status = fields.Str()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    owner_department = fields.Str(allow_none=True)
    submitter_type = fields.Str(allow_none=True)
    due_at = fields.DateTime(allow_none=True)
    # allow any extra keys returned by serialize_request so we can still
    # validate arbitrary payloads without raising validation errors
    extra = fields.Dict(load_only=True)

    @post_dump
    def remove_none(self, data, **kwargs):
        # drop fields with None values to keep responses lean
        return {k: v for k, v in data.items() if v is not None}
