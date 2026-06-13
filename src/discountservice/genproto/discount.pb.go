package genproto

import (
	context "context"
	reflect "reflect"
	sync "sync"

	grpc "google.golang.org/grpc"
	codes "google.golang.org/grpc/codes"
	status "google.golang.org/grpc/status"
	protoreflect "google.golang.org/protobuf/reflect/protoreflect"
	protoimpl "google.golang.org/protobuf/runtime/protoimpl"
)

const _ = protoimpl.EnforceVersion(20 - protoimpl.MinVersion)
const _ = protoimpl.EnforceVersion(protoimpl.MaxVersion - 20)

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
func (x *GetDiscountRequest) GetOriginalAmount() *Money {
	if x != nil { return x.OriginalAmount }
	return nil
}
func (x *GetDiscountRequest) GetCurrencyCode() string {
	if x != nil { return x.CurrencyCode }
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
func (x *GetDiscountResponse) GetOriginalAmount() *Money { if x != nil { return x.OriginalAmount }; return nil }
func (x *GetDiscountResponse) GetDiscountAmount() *Money { if x != nil { return x.DiscountAmount }; return nil }
func (x *GetDiscountResponse) GetFinalAmount() *Money { if x != nil { return x.FinalAmount }; return nil }
func (x *GetDiscountResponse) GetAppliedRule() string { if x != nil { return x.AppliedRule }; return "" }
func (x *GetDiscountResponse) GetDescription() string { if x != nil { return x.Description }; return "" }

var File_discount_proto protoreflect.FileDescriptor
var file_discount_proto_rawDesc = []byte{10,14,100,105,115,99,111,117,110,116,46,112,114,111,116,111,18,11,104,105,112,115,116,101,114,115,104,111,112,26,10,100,101,109,111,46,112,114,111,116,111,34,88,10,18,71,101,116,68,105,115,99,111,117,110,116,82,101,113,117,101,115,116,18,43,10,15,111,114,105,103,105,110,97,108,95,97,109,111,117,110,116,24,1,32,1,40,11,50,18,46,104,105,112,115,116,101,114,115,104,111,112,46,77,111,110,101,121,18,21,10,13,99,117,114,114,101,110,99,121,95,99,111,100,101,24,2,32,1,40,9,34,196,1,10,19,71,101,116,68,105,115,99,111,117,110,116,82,101,115,112,111,110,115,101,18,43,10,15,111,114,105,103,105,110,97,108,95,97,109,111,117,110,116,24,1,32,1,40,11,50,18,46,104,105,112,115,116,101,114,115,104,111,112,46,77,111,110,101,121,18,43,10,15,100,105,115,99,111,117,110,116,95,97,109,111,117,110,116,24,2,32,1,40,11,50,18,46,104,105,112,115,116,101,114,115,104,111,112,46,77,111,110,101,121,18,40,10,12,102,105,110,97,108,95,97,109,111,117,110,116,24,3,32,1,40,11,50,18,46,104,105,112,115,116,101,114,115,104,111,112,46,77,111,110,101,121,18,20,10,12,97,112,112,108,105,101,100,95,114,117,108,101,24,4,32,1,40,9,18,19,10,11,100,101,115,99,114,105,112,116,105,111,110,24,5,32,1,40,9,50,99,10,15,68,105,115,99,111,117,110,116,83,101,114,118,105,99,101,18,80,10,11,71,101,116,68,105,115,99,111,117,110,116,18,31,46,104,105,112,115,116,101,114,115,104,111,112,46,71,101,116,68,105,115,99,111,117,110,116,82,101,113,117,101,115,116,26,32,46,104,105,112,115,116,101,114,115,104,111,112,46,71,101,116,68,105,115,99,111,117,110,116,82,101,115,112,111,110,115,101,98,6,112,114,111,116,111,51}
var file_discount_proto_rawDescOnce sync.Once
var file_discount_proto_rawDescData = file_discount_proto_rawDesc
var file_discount_proto_msgTypes = make([]protoimpl.MessageInfo, 2)
var file_discount_proto_goTypes = []any{
	(*GetDiscountRequest)(nil),
	(*GetDiscountResponse)(nil),
	(*Money)(nil),
}
var file_discount_proto_depIdxs = []int32{2, 2, 0, 1}

func file_discount_proto_rawDescGZIP() []byte {
	file_discount_proto_rawDescOnce.Do(func() {
		file_discount_proto_rawDescData = protoimpl.X.CompressGZIP(file_discount_proto_rawDescData)
	})
	return file_discount_proto_rawDescData
}

func init() { file_discount_proto_init() }
func file_discount_proto_init() {
	if File_discount_proto != nil { return }
	if protoimpl.UnsafeEnabled {
		file_discount_proto_msgTypes[0].Exporter = func(v any, i int) any {
			switch v := v.(*GetDiscountRequest); i { case 0: return &v.state; case 1: return &v.sizeCache; case 2: return &v.unknownFields; default: return nil }
		}
		file_discount_proto_msgTypes[1].Exporter = func(v any, i int) any {
			switch v := v.(*GetDiscountResponse); i { case 0: return &v.state; case 1: return &v.sizeCache; case 2: return &v.unknownFields; default: return nil }
		}
	}
	type x struct{}
	out := protoimpl.TypeBuilder{
		File: protoimpl.DescBuilder{GoPackagePath: reflect.TypeOf(x{}).PkgPath(), RawDescriptor: file_discount_proto_rawDesc, NumMessages: 2, NumServices: 1},
		GoTypes: file_discount_proto_goTypes,
		DependencyIndexes: file_discount_proto_depIdxs,
		MessageInfos: file_discount_proto_msgTypes,
	}.Build()
	File_discount_proto = out.File
	file_discount_proto_rawDesc = nil
	file_discount_proto_goTypes = nil
	file_discount_proto_depIdxs = nil
}

const DiscountService_GetDiscount_FullMethodName = "/hipstershop.DiscountService/GetDiscount"

type DiscountServiceClient interface { GetDiscount(ctx context.Context, in *GetDiscountRequest, opts ...grpc.CallOption) (*GetDiscountResponse, error) }
type discountServiceClient struct { cc grpc.ClientConnInterface }
func NewDiscountServiceClient(cc grpc.ClientConnInterface) DiscountServiceClient { return &discountServiceClient{cc} }
func (c *discountServiceClient) GetDiscount(ctx context.Context, in *GetDiscountRequest, opts ...grpc.CallOption) (*GetDiscountResponse, error) { out := new(GetDiscountResponse); err := c.cc.Invoke(ctx, DiscountService_GetDiscount_FullMethodName, in, out, opts...); if err != nil { return nil, err }; return out, nil }

type DiscountServiceServer interface { GetDiscount(context.Context, *GetDiscountRequest) (*GetDiscountResponse, error); mustEmbedUnimplementedDiscountServiceServer() }
type UnimplementedDiscountServiceServer struct{}
func (UnimplementedDiscountServiceServer) GetDiscount(context.Context, *GetDiscountRequest) (*GetDiscountResponse, error) { return nil, status.Errorf(codes.Unimplemented, "method GetDiscount not implemented") }
func (UnimplementedDiscountServiceServer) mustEmbedUnimplementedDiscountServiceServer() {}
type UnsafeDiscountServiceServer interface { mustEmbedUnimplementedDiscountServiceServer() }
func RegisterDiscountServiceServer(s grpc.ServiceRegistrar, srv DiscountServiceServer) { s.RegisterService(&DiscountService_ServiceDesc, srv) }
func _DiscountService_GetDiscount_Handler(srv interface{}, ctx context.Context, dec func(interface{}) error, interceptor grpc.UnaryServerInterceptor) (interface{}, error) { in := new(GetDiscountRequest); if err := dec(in); err != nil { return nil, err }; if interceptor == nil { return srv.(DiscountServiceServer).GetDiscount(ctx, in) }; info := &grpc.UnaryServerInfo{Server: srv, FullMethod: DiscountService_GetDiscount_FullMethodName}; handler := func(ctx context.Context, req interface{}) (interface{}, error) { return srv.(DiscountServiceServer).GetDiscount(ctx, req.(*GetDiscountRequest)) }; return interceptor(ctx, in, info, handler) }
var DiscountService_ServiceDesc = grpc.ServiceDesc{ServiceName: "hipstershop.DiscountService", HandlerType: (*DiscountServiceServer)(nil), Methods: []grpc.MethodDesc{{MethodName: "GetDiscount", Handler: _DiscountService_GetDiscount_Handler}}, Streams: []grpc.StreamDesc{}, Metadata: "discount.proto"}

