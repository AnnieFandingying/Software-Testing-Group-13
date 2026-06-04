package genproto

import (
	reflect "reflect"
	sync "sync"

	protoreflect "google.golang.org/protobuf/reflect/protoreflect"
	protoimpl "google.golang.org/protobuf/runtime/protoimpl"
)

const _ = protoimpl.EnforceVersion(20 - protoimpl.MinVersion)
const _ = protoimpl.EnforceVersion(protoimpl.MaxVersion - 20)

type Money struct {
	state         protoimpl.MessageState
	sizeCache     protoimpl.SizeCache
	unknownFields protoimpl.UnknownFields

	CurrencyCode string `protobuf:"bytes,1,opt,name=currency_code,json=currencyCode,proto3" json:"currency_code,omitempty"`
	Units        int64  `protobuf:"varint,2,opt,name=units,proto3" json:"units,omitempty"`
	Nanos        int32  `protobuf:"varint,3,opt,name=nanos,proto3" json:"nanos,omitempty"`
}

func (x *Money) Reset()         { *x = Money{} }
func (x *Money) String() string { return protoimpl.X.MessageStringOf(x) }
func (*Money) ProtoMessage()    {}
func (x *Money) ProtoReflect() protoreflect.Message {
	mi := &file_discount_proto_msgTypes[0]
	if protoimpl.UnsafeEnabled && x != nil {
		ms := protoimpl.X.MessageStateOf(protoimpl.Pointer(x))
		if ms.LoadMessageInfo() == nil {
			ms.StoreMessageInfo(mi)
		}
		return ms
	}
	return mi.MessageOf(x)
}
func (x *Money) GetCurrencyCode() string {
	if x != nil {
		return x.CurrencyCode
	}
	return ""
}
func (x *Money) GetUnits() int64 {
	if x != nil {
		return x.Units
	}
	return 0
}
func (x *Money) GetNanos() int32 {
	if x != nil {
		return x.Nanos
	}
	return 0
}

type GetDiscountRequest struct {
	state         protoimpl.MessageState
	sizeCache     protoimpl.SizeCache
	unknownFields protoimpl.UnknownFields

	OriginalAmount *Money `protobuf:"bytes,1,opt,name=original_amount,json=originalAmount,proto3" json:"original_amount,omitempty"`
	CurrencyCode   string `protobuf:"bytes,2,opt,name=currency_code,json=currencyCode,proto3" json:"currency_code,omitempty"`
}

func (x *GetDiscountRequest) Reset()         { *x = GetDiscountRequest{} }
func (x *GetDiscountRequest) String() string { return protoimpl.X.MessageStringOf(x) }
func (*GetDiscountRequest) ProtoMessage()    {}
func (x *GetDiscountRequest) ProtoReflect() protoreflect.Message {
	mi := &file_discount_proto_msgTypes[1]
	if protoimpl.UnsafeEnabled && x != nil {
		ms := protoimpl.X.MessageStateOf(protoimpl.Pointer(x))
		if ms.LoadMessageInfo() == nil {
			ms.StoreMessageInfo(mi)
		}
		return ms
	}
	return mi.MessageOf(x)
}
func (x *GetDiscountRequest) GetOriginalAmount() *Money {
	if x != nil {
		return x.OriginalAmount
	}
	return nil
}
func (x *GetDiscountRequest) GetCurrencyCode() string {
	if x != nil {
		return x.CurrencyCode
	}
	return ""
}

type GetDiscountResponse struct {
	state         protoimpl.MessageState
	sizeCache     protoimpl.SizeCache
	unknownFields protoimpl.UnknownFields

	OriginalAmount *Money `protobuf:"bytes,1,opt,name=original_amount,json=originalAmount,proto3" json:"original_amount,omitempty"`
	DiscountAmount *Money `protobuf:"bytes,2,opt,name=discount_amount,json=discountAmount,proto3" json:"discount_amount,omitempty"`
	FinalAmount    *Money `protobuf:"bytes,3,opt,name=final_amount,json=finalAmount,proto3" json:"final_amount,omitempty"`
	AppliedRule    string `protobuf:"bytes,4,opt,name=applied_rule,json=appliedRule,proto3" json:"applied_rule,omitempty"`
	Description    string `protobuf:"bytes,5,opt,name=description,proto3" json:"description,omitempty"`
}

func (x *GetDiscountResponse) Reset()         { *x = GetDiscountResponse{} }
func (x *GetDiscountResponse) String() string { return protoimpl.X.MessageStringOf(x) }
func (*GetDiscountResponse) ProtoMessage()    {}
func (x *GetDiscountResponse) ProtoReflect() protoreflect.Message {
	mi := &file_discount_proto_msgTypes[2]
	if protoimpl.UnsafeEnabled && x != nil {
		ms := protoimpl.X.MessageStateOf(protoimpl.Pointer(x))
		if ms.LoadMessageInfo() == nil {
			ms.StoreMessageInfo(mi)
		}
		return ms
	}
	return mi.MessageOf(x)
}
func (x *GetDiscountResponse) GetOriginalAmount() *Money {
	if x != nil {
		return x.OriginalAmount
	}
	return nil
}
func (x *GetDiscountResponse) GetDiscountAmount() *Money {
	if x != nil {
		return x.DiscountAmount
	}
	return nil
}
func (x *GetDiscountResponse) GetFinalAmount() *Money {
	if x != nil {
		return x.FinalAmount
	}
	return nil
}
func (x *GetDiscountResponse) GetAppliedRule() string {
	if x != nil {
		return x.AppliedRule
	}
	return ""
}
func (x *GetDiscountResponse) GetDescription() string {
	if x != nil {
		return x.Description
	}
	return ""
}

var File_discount_proto protoreflect.FileDescriptor

var file_discount_proto_rawDesc = []byte{}
var file_discount_proto_rawDescOnce sync.Once
var file_discount_proto_msgTypes = make([]protoimpl.MessageInfo, 3)
var file_discount_proto_goTypes = []any{
	(*Money)(nil),
	(*GetDiscountRequest)(nil),
	(*GetDiscountResponse)(nil),
}
var file_discount_proto_depIdxs = []int32{
	0,
	0,
	0,
	1,
	2,
}

func file_discount_proto_rawDescGZIP() []byte {
	file_discount_proto_rawDescOnce.Do(func() {
		file_discount_proto_rawDesc = protoimpl.X.CompressGZIP(file_discount_proto_rawDesc)
	})
	return file_discount_proto_rawDesc
}

func init() {
	if File_discount_proto != nil {
		return
	}
	type x struct{}
	out := protoimpl.TypeBuilder{
		File: protoimpl.DescBuilder{
			GoPackagePath: reflect.TypeOf(x{}).PkgPath(),
			RawDescriptor: file_discount_proto_rawDesc,
			NumMessages:   3,
			NumServices:   1,
		},
		GoTypes:           file_discount_proto_goTypes,
		DependencyIndexes: file_discount_proto_depIdxs,
		MessageInfos:      file_discount_proto_msgTypes,
	}.Build()
	File_discount_proto = out.File
}
